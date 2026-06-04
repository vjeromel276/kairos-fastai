#!/usr/bin/env python3
"""
scripts/pipeline/full_sharadar_refresh.py
============================
Refresh any Sharadar table from the Nasdaq Data Link API. Designed as a
one-stop tool for a full Sharadar refresh; for the daily production loop,
prefer `sharadar_data_sync.py` (smaller surface area, faster).

Tables handled:
  SEP        - Daily stock prices                                  [incremental]
  DAILY      - Daily fundamental ratios                            [incremental]
  SF1        - Quarterly/Annual fundamentals                       [incremental]
  SF2        - Insider transactions                                [incremental]
  SF3        - Institutional holdings (long form)                  [incremental]
  SF3A       - Institutional holdings by ticker                    [incremental]
  SF3B       - Institutional holdings by investor                  [incremental]
  SFP        - Sharadar Fund Prices                                [incremental, opt-in]
  METRICS    - Daily snapshot metrics (52w hi/lo, MAs, betas)      [incremental]
  TICKERS    - Ticker metadata (sector, industry, listings)        [full reload]
  ACTIONS    - Corporate actions (splits, dividends)               [incremental]
  EVENTS     - Corporate event filings                             [incremental]
  SP500      - S&P 500 constituent changes                         [full reload]
  INDICATORS - Indicator metadata reference (no date field)        [full reload, opt-in]
  CALENDAR   - trading_calendar derived from distinct sep_base.date [local refresh]

Full reload is used where deletions matter (TICKERS) or where the table is a
small change-log/reference that's cheap to re-download (SP500, INDICATORS).
INDICATORS has no date column and barely changes, so it's opt-in only — you
must list it explicitly via --tables.

After refresh, the script refreshes `trading_calendar` from distinct
`sep_base.date` values so the calendar stays aligned with the retained market
data. Use `--skip-calendar` to disable that post-refresh step.

Usage:
    # Refresh everything that's stale (excluding INDICATORS)
    python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb

    # Check only (no download)
    python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --check-only

    # Refresh specific tables
    python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --tables METRICS TICKERS

    # Refresh INDICATORS reference table (must be explicit)
    python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --tables INDICATORS

    # Force re-download even if up to date
    python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --tables SF3 --force

Environment:
    NASDAQ_DATA_LINK_API_KEY: Your Nasdaq Data Link API key
"""

import argparse
import io
import logging
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import zipfile

import duckdb
import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

API_KEY_ENV = "NASDAQ_DATA_LINK_API_KEY"
BASE_URL = "https://data.nasdaq.com/api/v3/datatables/SHARADAR"
PAGE_SAFETY_LIMIT = 500  # ~5M rows max per table per run
BULK_EXPORT_POLL_SECONDS = 30.0
BULK_EXPORT_MAX_ATTEMPTS = 60
DEFAULT_BULK_DOWNLOAD_DIR = Path("data/downloads/full_refresh")
API_KEY_QUERY_RE = re.compile(r"((?:^|[?&\s])api_key=)[^&\s'\"<>)]+")
API_KEY_DICT_RE = re.compile(r"(['\"]api_key['\"]\s*:\s*['\"])[^'\"]+(['\"])")


def redact_api_key(value: object) -> str:
    """Redact Nasdaq API keys from URL and params-style exception text."""
    text = str(value)
    text = API_KEY_QUERY_RE.sub(r"\1<redacted>", text)
    return API_KEY_DICT_RE.sub(r"\1<redacted>\2", text)

TABLES: Dict[str, Dict] = {
    "SEP": {
        "db_table": "sep_base",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Daily stock prices",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date", "lastupdated"],
    },
    "DAILY": {
        "db_table": "daily",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Daily fundamental ratios (PE, PB, PS, EV/EBITDA)",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date", "lastupdated"],
    },
    "SF1": {
        "db_table": "sf1",
        "date_field": "lastupdated",
        "db_date_field": "lastupdated",
        "description": "Quarterly/Annual fundamentals",
        "reload_mode": "incremental",
        "use_gte": True,
        "date_columns": ["datekey", "reportperiod", "lastupdated"],
    },
    "SF2": {
        "db_table": "sf2",
        "date_field": "filingdate",
        "db_date_field": "filingdate",
        "description": "Insider transactions",
        "reload_mode": "incremental",
        "use_gte": True,
        "date_columns": ["filingdate", "transactiondate"],
    },
    "SFP": {
        "db_table": "sfp",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Sharadar Fund Prices (mutual funds, ETFs)",
        "reload_mode": "incremental",
        "use_gte": False,
        "opt_in_only": True,
        "date_columns": ["date", "lastupdated"],
    },
    "METRICS": {
        "db_table": "sharadar_metrics",
        "date_field": "lastupdated",
        "db_date_field": "lastupdated",
        "description": "Daily snapshot metrics (52w hi/lo, MAs, betas)",
        "reload_mode": "incremental",
        "use_gte": True,
        "date_columns": ["date", "lastupdated"],
    },
    "TICKERS": {
        "db_table": "tickers",
        "date_field": "lastupdated",
        "db_date_field": "lastupdated",
        "description": "Ticker metadata (sector, industry, listings)",
        "reload_mode": "full",
        "date_columns": [
            "lastupdated", "firstadded", "firstpricedate", "lastpricedate",
            "firstquarter", "lastquarter",
        ],
    },
    "ACTIONS": {
        "db_table": "sharadar_actions",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Corporate actions (splits, dividends)",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date"],
    },
    "EVENTS": {
        "db_table": "sharadar_events",
        "date_field": "date",
        "db_date_field": "date",
        "description": "Corporate event filings",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["date"],
    },
    "SF3": {
        "db_table": "sf3",
        "date_field": "calendardate",
        "db_date_field": "calendardate",
        "description": "Institutional holdings (long form)",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["calendardate"],
    },
    "SF3A": {
        "db_table": "sf3a",
        "date_field": "calendardate",
        "db_date_field": "calendardate",
        "description": "Institutional holdings by ticker",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["calendardate"],
    },
    "SF3B": {
        "db_table": "sf3b",
        "date_field": "calendardate",
        "db_date_field": "calendardate",
        "description": "Institutional holdings by investor",
        "reload_mode": "incremental",
        "use_gte": False,
        "date_columns": ["calendardate"],
    },
    "SP500": {
        "db_table": "sharadar_sp500",
        "date_field": "date",
        "db_date_field": "date",
        "description": "S&P 500 constituent changes",
        "reload_mode": "full",
        "date_columns": ["date"],
    },
    "INDICATORS": {
        "db_table": "sharadar_indicators",
        "description": "Indicator metadata reference (no date field)",
        "reload_mode": "full",
        "no_date_field": True,
        "opt_in_only": True,
        "date_columns": [],
    },
}

DEFAULT_TABLES = [t for t, cfg in TABLES.items() if not cfg.get("opt_in_only")]


def get_api_key() -> str:
    api_key = os.getenv(API_KEY_ENV)
    if not api_key:
        logger.error(f"Environment variable '{API_KEY_ENV}' not set.")
        sys.exit(1)
    return api_key


def get_local_max_date(conn: duckdb.DuckDBPyConnection, table_config: Dict) -> Optional[date]:
    db_table = table_config["db_table"]
    date_field = table_config["db_date_field"]

    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    if db_table not in tables:
        logger.info(f"  Table '{db_table}' does not exist locally")
        return None

    try:
        result = conn.execute(f"SELECT MAX({date_field}) FROM {db_table}").fetchone()
        if result and result[0]:
            v = result[0]
            if isinstance(v, datetime):
                return v.date()
            if isinstance(v, date):
                return v
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
        return None
    except Exception as e:
        logger.warning(f"  Error reading max({date_field}) from {db_table}: {e}")
        return None


def check_api_for_new_data(
    table_name: str,
    table_config: Dict,
    local_max: Optional[date],
    api_key: str,
) -> Tuple[bool, Optional[date]]:
    """Returns (has_new_data, api_max_date_observed)."""
    date_field = table_config["date_field"]
    url = f"{BASE_URL}/{table_name}.json"
    params = {
        "qopts.columns": date_field,
        "qopts.per_page": "100",
        "api_key": api_key,
    }

    if local_max:
        # use_gte tables intentionally refresh the max-date overlap so
        # same-date corrections are not skipped.
        check_date = (
            local_max
            if table_config.get("use_gte", False)
            else local_max + timedelta(days=1)
        )
        params[f"{date_field}.gte"] = check_date.strftime("%Y-%m-%d")

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json().get("datatable", {}).get("data", [])
        if not rows:
            return False, local_max

        api_max = None
        for row in rows:
            if not row[0]:
                continue
            d = datetime.strptime(str(row[0])[:10], "%Y-%m-%d").date()
            if api_max is None or d > api_max:
                api_max = d
        if api_max is None:
            return False, local_max
        return True, api_max
    except Exception as e:
        logger.warning(f"  Error checking API for {table_name}: {redact_api_key(e)}")
        return False, None


def download_paginated(
    table_name: str,
    table_config: Dict,
    since_date: Optional[date],
    api_key: str,
) -> Optional[pd.DataFrame]:
    """Download from API with pagination. since_date=None means full table."""
    date_field = table_config["date_field"]
    use_gte = table_config.get("use_gte", False)
    date_columns = table_config.get("date_columns", [])

    base_url = f"{BASE_URL}/{table_name}.csv"
    base_params = {"api_key": api_key, "qopts.per_page": "10000"}
    if since_date is not None:
        if use_gte:
            base_params[f"{date_field}.gte"] = since_date.strftime("%Y-%m-%d")
        else:
            next_date = since_date + timedelta(days=1)
            base_params[f"{date_field}.gte"] = next_date.strftime("%Y-%m-%d")

    logger.info(f"  Downloading {table_name} (paginated)...")

    all_dfs: List[pd.DataFrame] = []
    cursor_id: Optional[str] = None
    page = 1
    total_rows = 0

    try:
        while True:
            params = base_params.copy()
            if cursor_id:
                params["qopts.cursor_id"] = cursor_id
            resp = requests.get(base_url, params=params, timeout=180)
            resp.raise_for_status()

            csv_content = resp.text
            if not csv_content.strip():
                break

            df_page = pd.read_csv(
                io.StringIO(csv_content),
                parse_dates=date_columns,
                low_memory=False,
            )
            if df_page.empty:
                break

            rows_this = len(df_page)
            total_rows += rows_this
            all_dfs.append(df_page)
            logger.info(f"    Page {page}: {rows_this:,} rows (total: {total_rows:,})")

            if rows_this < 10000:
                break

            # Get next cursor via JSON endpoint
            json_url = f"{BASE_URL}/{table_name}.json"
            json_resp = requests.get(json_url, params=params, timeout=60)
            json_resp.raise_for_status()
            cursor_id = json_resp.json().get("meta", {}).get("next_cursor_id")
            if not cursor_id:
                break

            if page >= PAGE_SAFETY_LIMIT:
                raise RuntimeError(
                    f"Pagination safety limit reached for {table_name}: "
                    f"{PAGE_SAFETY_LIMIT} pages downloaded and API still returned next_cursor_id"
                )

            page += 1

        if not all_dfs:
            logger.warning(f"  No data downloaded")
            return None

        df = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"  Total: {len(df):,} rows across {page} page(s)")
        return df
    except Exception as e:
        logger.error(f"  Download failed: {redact_api_key(e)}")
        return None


def sql_literal(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def write_response_to_file(resp, output_path: Path) -> None:
    with output_path.open("wb") as f:
        if hasattr(resp, "iter_content"):
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        else:
            f.write(resp.content)


def download_bulk_export_zip(
    table_name: str,
    api_key: str,
    download_root: Path,
    poll_seconds: float = BULK_EXPORT_POLL_SECONDS,
    max_attempts: int = BULK_EXPORT_MAX_ATTEMPTS,
) -> Path:
    """Request Nasdaq bulk export and download the fresh zipped CSV file."""
    run_id = f"{datetime.utcnow():%Y%m%dT%H%M%SZ}_{table_name.lower()}_{uuid.uuid4().hex[:8]}"
    run_dir = download_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    export_url = f"{BASE_URL}/{table_name}.json"
    export_params = {"api_key": api_key, "qopts.export": "true"}
    zip_path = run_dir / f"{table_name.lower()}_bulk.zip"

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(export_url, params=export_params, timeout=60)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            raise RuntimeError(
                f"Bulk export status request failed for {table_name}: {redact_api_key(e)}"
            ) from e

        bulk = payload.get("datatable_bulk_download", {})
        file_info = bulk.get("file", {}) or {}
        status = str(file_info.get("status") or "").lower()
        link = file_info.get("link")
        logger.info(f"  Bulk export status for {table_name}: {status or 'unknown'}")

        if status == "fresh" and link:
            try:
                download_resp = requests.get(link, timeout=600, stream=True)
                download_resp.raise_for_status()
                write_response_to_file(download_resp, zip_path)
            except Exception as e:
                raise RuntimeError(
                    f"Bulk export download failed for {table_name}: {redact_api_key(e)}"
                ) from e

            if zip_path.stat().st_size == 0:
                raise RuntimeError(f"Bulk export download for {table_name} produced an empty file")
            logger.info(f"  Downloaded bulk export to {zip_path}")
            return zip_path

        if attempt < max_attempts:
            time.sleep(poll_seconds)

    raise RuntimeError(
        f"Bulk export for {table_name} was not fresh after {max_attempts} attempt(s)"
    )


def extract_bulk_csv(zip_path: Path) -> Path:
    """Extract the single CSV from a Nasdaq bulk export zip."""
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError(f"Bulk export file is not a zip archive: {zip_path}")

    extract_dir = zip_path.parent / "extracted"
    extract_dir.mkdir(exist_ok=False)

    with zipfile.ZipFile(zip_path) as zf:
        csv_members = [
            member
            for member in zf.namelist()
            if not member.endswith("/") and member.lower().endswith(".csv")
        ]
        if len(csv_members) != 1:
            raise RuntimeError(
                f"Expected exactly one CSV in {zip_path}, found {len(csv_members)}"
            )
        csv_path = extract_dir / Path(csv_members[0]).name
        with zf.open(csv_members[0]) as src, csv_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)

    if not csv_path.exists():
        raise RuntimeError(f"Bulk export CSV was not extracted: {csv_path}")
    return csv_path


def insert_incremental(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    table_config: Dict,
) -> int:
    """
    Append new rows, refreshing gte overlap rows atomically.
    Returns net rows added.
    """
    db_table = table_config["db_table"]
    date_field = table_config["db_date_field"]
    use_gte = table_config.get("use_gte", False)

    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    if db_table not in tables:
        logger.info(f"  Creating table '{db_table}'...")
        conn.execute(f"CREATE TABLE {db_table} AS SELECT * FROM df")
        return conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]

    local_max = get_local_max_date(conn, table_config)
    before = conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]

    if local_max and use_gte:
        overlap_start = local_max.isoformat()
        logger.info(f"  Refreshing overlap window from {overlap_start}")
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(f"""
                DELETE FROM {db_table}
                WHERE {date_field} >= DATE '{overlap_start}'
            """)
            conn.execute(f"""
                INSERT INTO {db_table}
                SELECT DISTINCT * FROM df
                WHERE {date_field} >= DATE '{overlap_start}'
            """)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    else:
        filter_clause = (
            f"WHERE {date_field} > DATE '{local_max.isoformat()}'"
            if local_max else ""
        )
        conn.execute(f"""
            INSERT INTO {db_table}
            SELECT DISTINCT * FROM df
            {filter_clause}
        """)

    after = conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]
    return after - before


def replace_full(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    table_config: Dict,
) -> Tuple[int, int]:
    """Replace a full-reload table without dropping the old table until swap time."""
    db_table = table_config["db_table"]
    temp_table = f"tmp_{db_table}_replacement_{uuid.uuid4().hex}"
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    before = (
        conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]
        if db_table in tables else 0
    )

    temp_created = False
    try:
        conn.execute(f"CREATE TEMP TABLE {temp_table} AS SELECT * FROM df")
        temp_created = True
        after = conn.execute(f"SELECT COUNT(*) FROM {temp_table}").fetchone()[0]
        expected_rows = len(df)
        if after != expected_rows:
            raise RuntimeError(
                f"Replacement row-count mismatch for {db_table}: "
                f"expected {expected_rows}, got {after}"
            )

        temp_columns = [
            column[0]
            for column in conn.execute(f"SELECT * FROM {temp_table} LIMIT 0").description
        ]
        expected_columns = list(df.columns)
        if temp_columns != expected_columns:
            raise RuntimeError(
                f"Replacement column mismatch for {db_table}: "
                f"expected {expected_columns}, got {temp_columns}"
            )

        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(f"DROP TABLE IF EXISTS {db_table}")
            conn.execute(f"CREATE TABLE {db_table} AS SELECT * FROM {temp_table}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return before, after
    finally:
        if temp_created:
            conn.execute(f"DROP TABLE IF EXISTS {temp_table}")


def replace_full_from_staging_table(
    conn: duckdb.DuckDBPyConnection,
    staging_table: str,
    table_config: Dict,
) -> Tuple[int, int]:
    """Atomically replace a full-reload table from a validated staging table."""
    db_table = table_config["db_table"]
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    before = (
        conn.execute(f"SELECT COUNT(*) FROM {db_table}").fetchone()[0]
        if db_table in tables else 0
    )
    after = conn.execute(f"SELECT COUNT(*) FROM {staging_table}").fetchone()[0]
    staging_columns = [
        column[0]
        for column in conn.execute(f"SELECT * FROM {staging_table} LIMIT 0").description
    ]
    if not staging_columns:
        raise RuntimeError(f"Bulk replacement for {db_table} produced no columns")

    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {db_table}")
        conn.execute(f"CREATE TABLE {db_table} AS SELECT * FROM {staging_table}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return before, after


def replace_full_from_csv(
    conn: duckdb.DuckDBPyConnection,
    csv_path: Path,
    table_config: Dict,
) -> Tuple[int, int]:
    """Load a bulk-export CSV into staging, then atomically replace the table."""
    db_table = table_config["db_table"]
    temp_table = f"tmp_{db_table}_bulk_{uuid.uuid4().hex}"
    temp_created = False
    try:
        conn.execute(f"""
            CREATE TEMP TABLE {temp_table} AS
            SELECT * FROM read_csv_auto({sql_literal(csv_path)}, header = true)
        """)
        temp_created = True
        return replace_full_from_staging_table(conn, temp_table, table_config)
    finally:
        if temp_created:
            conn.execute(f"DROP TABLE IF EXISTS {temp_table}")


def replace_full_from_bulk_export(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    table_config: Dict,
    api_key: str,
    download_root: Path,
    keep_downloads: bool = False,
    poll_seconds: float = BULK_EXPORT_POLL_SECONDS,
    max_attempts: int = BULK_EXPORT_MAX_ATTEMPTS,
) -> Tuple[int, int]:
    """
    Download a full table via Nasdaq bulk export, ingest from local CSV, and clean up.

    Downloads are deleted only after successful ingestion. Failed runs leave files in
    place so they can be inspected or ingested manually without another export request.
    """
    zip_path = download_bulk_export_zip(
        table_name,
        api_key,
        download_root,
        poll_seconds=poll_seconds,
        max_attempts=max_attempts,
    )
    run_dir = zip_path.parent
    success = False
    try:
        csv_path = extract_bulk_csv(zip_path)
        before, after = replace_full_from_csv(conn, csv_path, table_config)
        success = True
        return before, after
    finally:
        if success and not keep_downloads:
            shutil.rmtree(run_dir, ignore_errors=True)


def refresh_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    table_config: Dict,
    api_key: str,
    check_only: bool,
    force: bool,
    download_root: Path = DEFAULT_BULK_DOWNLOAD_DIR,
    keep_downloads: bool = False,
    bulk_poll_seconds: float = BULK_EXPORT_POLL_SECONDS,
    bulk_max_attempts: int = BULK_EXPORT_MAX_ATTEMPTS,
) -> Dict:
    mode = table_config["reload_mode"]
    result = {
        "table": table_name,
        "db_table": table_config["db_table"],
        "mode": mode,
        "local_max": None,
        "api_max": None,
        "rows_before": None,
        "rows_after": None,
        "rows_added": 0,
        "status": "unknown",
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"{table_name} [{mode}]: {table_config['description']}")
    logger.info(f"{'='*60}")

    no_date = table_config.get("no_date_field", False)
    if mode == "full":
        if no_date:
            local_max = None
            logger.info(f"  No date field; will full-reload when selected")
        else:
            local_max = get_local_max_date(conn, table_config)
            logger.info(f"  Local max {table_config['db_date_field']}: {local_max or 'No data'}")
        api_max = None
        has_new = True
        logger.info(f"  Full-reload table; skipping incremental staleness check")
    else:
        local_max = get_local_max_date(conn, table_config)
        logger.info(f"  Local max {table_config['db_date_field']}: {local_max or 'No data'}")
        has_new, api_max = check_api_for_new_data(table_name, table_config, local_max, api_key)
        if api_max:
            logger.info(f"  API max {table_config['date_field']}: {api_max}")
    result["local_max"] = local_max
    result["api_max"] = api_max

    if not has_new and not force:
        if api_max is None:
            logger.info(f"  ? Could not determine API status")
            result["status"] = "check_failed"
        else:
            logger.info(f"  + Already up to date")
            result["status"] = "up_to_date"
        return result

    if force:
        logger.info(f"  Force download requested")
    elif mode == "full":
        logger.info(f"  Full reload scheduled")
    else:
        logger.info(f"  New data available")

    if check_only:
        logger.info(f"  (check-only mode, skipping download)")
        result["status"] = "needs_update"
        return result

    if mode == "full":
        try:
            before, after = replace_full_from_bulk_export(
                conn,
                table_name,
                table_config,
                api_key,
                download_root,
                keep_downloads=keep_downloads,
                poll_seconds=bulk_poll_seconds,
                max_attempts=bulk_max_attempts,
            )
        except Exception as e:
            logger.error(f"  Bulk full reload failed: {redact_api_key(e)}")
            result["status"] = "download_failed"
            return result
        result["rows_before"] = before
        result["rows_after"] = after
        result["rows_added"] = after - before
        logger.info(f"  + Replaced table: {before:,} -> {after:,} rows ({after - before:+,})")
    else:
        df = download_paginated(table_name, table_config, local_max, api_key)

        if df is None:
            result["status"] = "download_failed"
            return result

        added = insert_incremental(conn, df, table_config)
        result["rows_added"] = added
        result["rows_after"] = conn.execute(
            f"SELECT COUNT(*) FROM {table_config['db_table']}"
        ).fetchone()[0]
        new_max = get_local_max_date(conn, table_config)
        result["local_max"] = new_max
        logger.info(f"  + Added {added:,} rows, new max: {new_max}")

    result["status"] = "updated"
    return result


def print_summary(results: List[Dict]):
    logger.info(f"\n{'='*70}")
    logger.info("REFRESH SUMMARY")
    logger.info(f"{'='*70}")
    icons = {
        "up_to_date": "+",
        "updated": "+",
        "needs_update": "!",
        "download_failed": "X",
        "check_failed": "?",
    }
    for r in results:
        icon = icons.get(r["status"], "?")
        local_str = str(r["local_max"]) if r["local_max"] else "None"
        logger.info(
            f"{icon} {r['table']:8} [{r['mode']:11}] | "
            f"Local: {local_str:12} | Status: {r['status']}"
        )
        if r["mode"] == "full" and r["rows_before"] is not None:
            logger.info(
                f"    rows: {r['rows_before']:,} -> {r['rows_after']:,} "
                f"({r['rows_added']:+,})"
            )
        elif r["rows_added"]:
            logger.info(f"    +{r['rows_added']:,} rows")
    logger.info(f"{'='*70}\n")


def refresh_trading_calendar(
    conn: duckdb.DuckDBPyConnection,
    source_table: str = "sep_base",
    calendar_table: str = "trading_calendar",
    check_only: bool = False,
) -> Dict:
    """Refresh trading_calendar from distinct source price dates."""
    result = {
        "table": calendar_table,
        "source_table": source_table,
        "rows_before": 0,
        "rows_after": 0,
        "old_max": None,
        "new_max": None,
        "status": "unknown",
    }

    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    if source_table not in tables:
        logger.warning(f"Trading calendar source table '{source_table}' does not exist")
        result["status"] = "missing_source"
        return result

    if calendar_table in tables:
        before = conn.execute(
            f"SELECT COUNT(*), MIN(trading_date), MAX(trading_date) FROM {calendar_table}"
        ).fetchone()
        result["rows_before"] = before[0]
        result["old_max"] = before[2]

    after_preview = conn.execute(
        f"SELECT COUNT(DISTINCT date), MIN(date), MAX(date) FROM {source_table}"
    ).fetchone()
    result["rows_after"] = after_preview[0]
    result["new_max"] = after_preview[2]

    logger.info(f"\n{'='*70}")
    logger.info("TRADING CALENDAR")
    logger.info(f"{'='*70}")
    logger.info(
        f"  Source {source_table}: {after_preview[0]:,} dates "
        f"({after_preview[1]} -> {after_preview[2]})"
    )

    if check_only:
        result["status"] = "needs_update" if result["old_max"] != result["new_max"] else "up_to_date"
        logger.info(f"  (check-only mode, status: {result['status']})")
        return result

    conn.execute(f"""
        CREATE OR REPLACE TABLE {calendar_table} AS
        SELECT DISTINCT CAST(date AS DATE) AS trading_date
        FROM {source_table}
        WHERE date IS NOT NULL
        ORDER BY trading_date
    """)
    result["status"] = "updated"
    logger.info(
        f"  Updated {calendar_table}: {result['rows_before']:,} -> "
        f"{result['rows_after']:,} rows, max {result['old_max']} -> {result['new_max']}"
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Refresh slow-moving Sharadar tables (METRICS, TICKERS, ACTIONS, EVENTS, SF3*, SP500)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Refresh all stale tables
  python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb

  # Check only (show what would update)
  python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --check-only

  # Refresh just metrics and tickers
  python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --tables METRICS TICKERS

  # Force re-download (ignore staleness check)
  python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --tables SF3 --force
""",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=list(TABLES.keys()),
        default=DEFAULT_TABLES,
        help=f"Tables to refresh (default: {', '.join(DEFAULT_TABLES)}; "
             f"opt-in only: {', '.join(t for t in TABLES if t not in DEFAULT_TABLES)})",
    )
    parser.add_argument("--check-only", action="store_true", help="Only check, don't download")
    parser.add_argument("--force", action="store_true", help="Force download even if up to date")
    parser.add_argument(
        "--skip-calendar",
        action="store_true",
        help="Do not refresh trading_calendar from sep_base after refresh"
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=DEFAULT_BULK_DOWNLOAD_DIR,
        help="Directory for temporary full-refresh bulk export downloads",
    )
    parser.add_argument(
        "--keep-downloads",
        action="store_true",
        help="Keep full-refresh bulk export files after successful ingestion",
    )
    parser.add_argument(
        "--bulk-poll-seconds",
        type=float,
        default=BULK_EXPORT_POLL_SECONDS,
        help="Seconds to wait between bulk export status checks",
    )
    parser.add_argument(
        "--bulk-max-attempts",
        type=int,
        default=BULK_EXPORT_MAX_ATTEMPTS,
        help="Maximum bulk export status checks before failing",
    )

    args = parser.parse_args()

    api_key = get_api_key()

    logger.info(f"\n{'='*70}")
    logger.info("SHARADAR SLOW-TABLE REFRESH v2")
    logger.info(f"{'='*70}")
    logger.info(f"Database: {args.db}")
    logger.info(f"Tables: {', '.join(args.tables)}")
    logger.info(f"Mode: {'Check only' if args.check_only else 'Refresh'}")

    conn = duckdb.connect(args.db)

    results: List[Dict] = []
    for table_name in args.tables:
        result = refresh_table(
            conn=conn,
            table_name=table_name,
            table_config=TABLES[table_name],
            api_key=api_key,
            check_only=args.check_only,
            force=args.force,
            download_root=args.download_dir,
            keep_downloads=args.keep_downloads,
            bulk_poll_seconds=args.bulk_poll_seconds,
            bulk_max_attempts=args.bulk_max_attempts,
        )
        results.append(result)

    calendar_result = None
    if not args.skip_calendar:
        calendar_result = refresh_trading_calendar(
            conn=conn,
            check_only=args.check_only,
        )

    conn.close()

    print_summary(results)
    if calendar_result:
        logger.info(
            "Calendar: %s | rows %s -> %s | max %s -> %s",
            calendar_result["status"],
            calendar_result["rows_before"],
            calendar_result["rows_after"],
            calendar_result["old_max"],
            calendar_result["new_max"],
        )

    failed = any(r["status"] in ("download_failed", "check_failed") for r in results)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
