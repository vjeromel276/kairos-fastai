#!/usr/bin/env python3
"""
Pre-model source freshness gate.

This workflow is intended to run before feature builds, training, evaluation,
or backtests. It checks the standard model source tables, updates refreshable
tables through the routine sync path, refreshes trading_calendar from SEP, and
fails closed if required source data is still stale.
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sharadar_data_sync as sync  # noqa: E402


logger = logging.getLogger(__name__)

MODEL_REQUIRED_TABLES = list(sync.DEFAULT_TABLES)
FAIL_STATUSES = {"download_failed", "check_failed"}
PENDING_STATUSES = {"needs_update", "needs_bootstrap"}


def coerce_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def table_exists(conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    return table_name in tables


def reference_report_result(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    table_config: Dict,
) -> Dict:
    local_max = None
    if not table_config.get("no_date_field", False):
        local_max = sync.get_local_max_date(conn, table_config)

    return {
        "table": table_name,
        "db_table": table_config["db_table"],
        "mode": table_config.get("reload_mode", "incremental"),
        "local_max": local_max,
        "post_local_max": local_max,
        "api_max": None,
        "has_new_data": True,
        "rows_before": None,
        "rows_after": None,
        "rows_added": 0,
        "status": "needs_reference_refresh",
    }


def add_post_sync_state(
    conn: duckdb.DuckDBPyConnection,
    result: Dict,
    table_config: Dict,
) -> None:
    if table_config.get("no_date_field", False):
        result["post_local_max"] = None
        result["table_exists"] = table_exists(conn, table_config["db_table"])
        return

    result["post_local_max"] = sync.get_local_max_date(conn, table_config)


def assess_result(result: Dict, table_config: Dict, max_staleness_days: int) -> List[str]:
    table_name = result["table"]
    status = result["status"]
    blockers: List[str] = []

    if status in FAIL_STATUSES:
        blockers.append(f"{table_name} failed with status {status}")
    elif status in PENDING_STATUSES:
        blockers.append(f"{table_name} still requires {status.replace('_', ' ')}")
    elif status == "needs_reference_refresh":
        blockers.append(f"{table_name} requires reference refresh before model use")

    if table_config.get("no_date_field", False):
        if not result.get("table_exists", False):
            blockers.append(f"{table_name} source table is missing")
        return blockers

    local_max = coerce_date(result.get("post_local_max") or result.get("local_max"))
    api_max = coerce_date(result.get("api_max"))

    if local_max is None:
        blockers.append(f"{table_name} has no local max date")
        return blockers

    if api_max is not None:
        lag_days = (api_max - local_max).days
        if lag_days > max_staleness_days:
            blockers.append(
                f"{table_name} is {lag_days} day(s) behind API max {api_max}; "
                f"allowed lag is {max_staleness_days}"
            )

    return blockers


def run_gate(
    conn: duckdb.DuckDBPyConnection,
    api_key: str,
    selected_tables: List[str],
    check_only: bool = False,
    max_staleness_days: int = 0,
    reference_policy: str = "refresh",
    download_root: Path = sync.DEFAULT_BULK_DOWNLOAD_DIR,
    keep_downloads: bool = False,
    bulk_poll_seconds: float = sync.BULK_EXPORT_POLL_SECONDS,
    bulk_max_attempts: int = sync.BULK_EXPORT_MAX_ATTEMPTS,
    page_safety_limit: Optional[int] = None,
) -> Dict:
    results: List[Dict] = []

    for table_name in selected_tables:
        table_config = sync.TABLES[table_name]
        mode = table_config.get("reload_mode", "incremental")

        if mode == "full" and reference_policy == "report":
            logger.info("")
            logger.info("=" * 50)
            logger.info(f"{table_name} [full]: reference refresh required by policy")
            logger.info("=" * 50)
            result = reference_report_result(conn, table_name, table_config)
        else:
            result = sync.sync_table(
                conn=conn,
                table_name=table_name,
                table_config=table_config,
                api_key=api_key,
                check_only=check_only,
                force=False,
                download_root=download_root,
                keep_downloads=keep_downloads,
                bulk_poll_seconds=bulk_poll_seconds,
                bulk_max_attempts=bulk_max_attempts,
                page_safety_limit=page_safety_limit,
            )
            add_post_sync_state(conn, result, table_config)

        results.append(result)

    calendar_result = None
    if "SEP" in selected_tables:
        sep_result = next((r for r in results if r["table"] == "SEP"), None)
        if sep_result and sep_result["status"] not in FAIL_STATUSES | PENDING_STATUSES:
            calendar_result = sync.refresh_trading_calendar(conn, check_only=check_only)
        else:
            logger.warning("Skipping trading_calendar refresh because SEP is not model-ready")

    blockers: List[str] = []
    for result in results:
        blockers.extend(
            assess_result(result, sync.TABLES[result["table"]], max_staleness_days)
        )

    if calendar_result:
        if calendar_result["status"] == "missing_source":
            blockers.append("trading_calendar could not be refreshed because sep_base is missing")
        elif check_only and calendar_result["status"] == "needs_update":
            blockers.append("trading_calendar needs refresh before model use")

    return {
        "passed": not blockers,
        "results": results,
        "calendar_result": calendar_result,
        "blockers": blockers,
    }


def print_gate_summary(gate_result: Dict) -> None:
    logger.info("")
    logger.info("=" * 60)
    logger.info("PRE-MODEL FRESHNESS SUMMARY")
    logger.info("=" * 60)

    for result in gate_result["results"]:
        local_max = result.get("post_local_max") or result.get("local_max")
        logger.info(
            "%-10s %-24s local=%-12s status=%s",
            result["table"],
            f"({result['db_table']})",
            str(local_max) if local_max else "None",
            result["status"],
        )

    calendar_result = gate_result.get("calendar_result")
    if calendar_result:
        logger.info(
            "Calendar   rows %s -> %s | max %s -> %s | status=%s",
            calendar_result["rows_before"],
            calendar_result["rows_after"],
            calendar_result["old_max"],
            calendar_result["new_max"],
            calendar_result["status"],
        )

    if gate_result["blockers"]:
        logger.error("Model freshness gate failed:")
        for blocker in gate_result["blockers"]:
            logger.error("  - %s", blocker)
    else:
        logger.info("Model freshness gate passed.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check and update required Sharadar source tables before model runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Update required source tables and fail if any remain stale
  python scripts/pipeline/pre_model_freshness_gate.py --db data/kairos-fastai.duckdb

  # Report what would block a model run without mutating data
  python scripts/pipeline/pre_model_freshness_gate.py --db data/kairos-fastai.duckdb --check-only

  # Allow one day of lag behind the API max date
  python scripts/pipeline/pre_model_freshness_gate.py --db data/kairos-fastai.duckdb --max-staleness-days 1

Default model-required tables: {', '.join(MODEL_REQUIRED_TABLES)}
""",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=list(sync.TABLES.keys()),
        default=MODEL_REQUIRED_TABLES,
        help="Required tables to check before model use",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check freshness without downloading or rebuilding data",
    )
    parser.add_argument(
        "--max-staleness-days",
        type=int,
        default=0,
        help="Allowed lag, in calendar days, behind the API max date after sync",
    )
    parser.add_argument(
        "--reference-policy",
        choices=["refresh", "report"],
        default="refresh",
        help="Refresh full-reference tables or report them as blockers",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=sync.DEFAULT_BULK_DOWNLOAD_DIR,
        help="Directory for temporary bulk export downloads",
    )
    parser.add_argument(
        "--keep-downloads",
        action="store_true",
        help="Keep bulk export files after successful ingestion",
    )
    parser.add_argument(
        "--bulk-poll-seconds",
        type=float,
        default=sync.BULK_EXPORT_POLL_SECONDS,
        help="Seconds to wait between bulk export status checks",
    )
    parser.add_argument(
        "--bulk-max-attempts",
        type=int,
        default=sync.BULK_EXPORT_MAX_ATTEMPTS,
        help="Maximum bulk export status checks before failing",
    )
    parser.add_argument(
        "--page-safety-limit",
        type=int,
        default=sync.PAGE_SAFETY_LIMIT,
        help="Maximum 10,000-row pages to download for one incremental table before failing",
    )
    args = parser.parse_args()

    if args.max_staleness_days < 0:
        parser.error("--max-staleness-days must be >= 0")

    api_key = sync.get_api_key()

    logger.info("")
    logger.info("=" * 60)
    logger.info("PRE-MODEL SOURCE FRESHNESS GATE")
    logger.info("=" * 60)
    logger.info("Database: %s", args.db)
    logger.info("Tables: %s", ", ".join(args.tables))
    logger.info("Mode: %s", "Check only" if args.check_only else "Update")
    logger.info("Reference policy: %s", args.reference_policy)

    conn = duckdb.connect(args.db)
    try:
        gate_result = run_gate(
            conn=conn,
            api_key=api_key,
            selected_tables=args.tables,
            check_only=args.check_only,
            max_staleness_days=args.max_staleness_days,
            reference_policy=args.reference_policy,
            download_root=args.download_dir,
            keep_downloads=args.keep_downloads,
            bulk_poll_seconds=args.bulk_poll_seconds,
            bulk_max_attempts=args.bulk_max_attempts,
            page_safety_limit=args.page_safety_limit,
        )
    finally:
        conn.close()

    print_gate_summary(gate_result)
    return 0 if gate_result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
