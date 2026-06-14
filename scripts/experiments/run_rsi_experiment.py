#!/usr/bin/env python3
"""Reproducible one-ticker RSI experiment driver."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments import build_rsi_one_ticker_dataset as builder  # noqa: E402
from scripts.experiments import train_rsi_one_ticker_baselines as trainer  # noqa: E402
from scripts.pipeline import pre_model_freshness_gate  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_METRICS_DIR = Path("data/experiments/rsi")
REAL_DB_PATH = ROOT / "data" / "kairos-fastai.duckdb"


def default_metrics_path(ticker: str) -> Path:
    return DEFAULT_METRICS_DIR / f"{ticker.lower()}_rsi_feature_comparison.json"


def is_real_project_db(db_path: Path) -> bool:
    return db_path.resolve() == REAL_DB_PATH.resolve()


def raise_if_freshness_failed(gate_result: dict) -> None:
    if gate_result["passed"]:
        return
    blockers = "; ".join(gate_result["blockers"])
    raise RuntimeError(f"Source freshness gate failed: {blockers}")


def run_source_freshness_gate(db_path: Path) -> None:
    api_key = pre_model_freshness_gate.sync.get_api_key()
    conn = duckdb.connect(str(db_path))
    try:
        gate_result = pre_model_freshness_gate.run_gate(
            conn=conn,
            api_key=api_key,
            selected_tables=pre_model_freshness_gate.MODEL_REQUIRED_TABLES,
            check_only=False,
        )
    finally:
        conn.close()
    raise_if_freshness_failed(gate_result)


def maybe_run_source_freshness_gate(
    db_path: Path,
    skip_freshness_check: bool = False,
) -> None:
    if skip_freshness_check:
        logger.info("Skipping source freshness gate by request")
        return
    if not is_real_project_db(db_path):
        logger.info("Skipping source freshness gate for non-project DB: %s", db_path)
        return
    run_source_freshness_gate(db_path)


def run_experiment(
    db_path: Path,
    ticker: str,
    train_end: str,
    validation_end: str,
    test_end: str,
    output_table: str = builder.DEFAULT_OUTPUT_TABLE,
    metrics_json: Path | None = None,
    source_table: str = builder.DEFAULT_SOURCE_TABLE,
    train_start: str | None = None,
    validation_start: str | None = None,
    test_start: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
    rsi_window: int = builder.DEFAULT_RSI_WINDOW,
    horizon_days: int = builder.DEFAULT_HORIZON_DAYS,
    skip_freshness_check: bool = False,
) -> dict:
    ticker = ticker.upper()
    metrics_path = metrics_json or default_metrics_path(ticker)
    maybe_run_source_freshness_gate(
        db_path,
        skip_freshness_check=skip_freshness_check,
    )

    conn = duckdb.connect(str(db_path))
    try:
        dataset = builder.build_one_ticker_dataset(
            conn,
            ticker=ticker,
            source_table=source_table,
            rsi_window=rsi_window,
            horizon_days=horizon_days,
            feature_set=builder.FEATURE_SET_ALL,
        )
        rows_written = builder.write_dataset_table(
            conn,
            dataset,
            output_table=output_table,
        )
        summary = trainer.run_feature_set_comparison(
            conn,
            ticker=ticker,
            table_name=output_table,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            test_start=test_start,
            test_end=test_end,
            embargo=embargo,
            embargo_unit=embargo_unit,
        )
    finally:
        conn.close()

    trainer.write_metrics_json(summary, metrics_path)
    print(f"Output table: {output_table}")
    print(f"Rows written: {rows_written}")
    print(f"Metrics JSON: {metrics_path}")
    return {
        "output_table": output_table,
        "rows_written": rows_written,
        "metrics_json": str(metrics_path),
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a one-ticker RSI dataset and run A/B/C/D baseline comparisons",
    )
    parser.add_argument("--db", required=True, type=Path, help="Path to DuckDB database")
    parser.add_argument("--ticker", required=True, help="Ticker to run, for example AAPL")
    parser.add_argument("--train-start", default=None, help="Optional train start date")
    parser.add_argument("--train-end", required=True, help="Train window end date")
    parser.add_argument("--validation-start", default=None, help="Optional validation start date")
    parser.add_argument("--validation-end", required=True, help="Validation window end date")
    parser.add_argument("--test-start", default=None, help="Optional test start date")
    parser.add_argument("--test-end", required=True, help="Test window end date")
    parser.add_argument(
        "--output-table",
        default=builder.DEFAULT_OUTPUT_TABLE,
        help=f"Output table to replace (default: {builder.DEFAULT_OUTPUT_TABLE})",
    )
    parser.add_argument(
        "--metrics-json",
        type=Path,
        default=None,
        help="Metrics JSON path; defaults under data/experiments/rsi",
    )
    parser.add_argument(
        "--source-table",
        default=builder.DEFAULT_SOURCE_TABLE,
        help=f"Source table to read (default: {builder.DEFAULT_SOURCE_TABLE})",
    )
    parser.add_argument(
        "--embargo",
        type=int,
        default=None,
        help="Embargo length; defaults to the time split helper default",
    )
    parser.add_argument(
        "--embargo-unit",
        choices=["calendar", "trading"],
        default="trading",
        help="Embargo unit",
    )
    parser.add_argument(
        "--skip-freshness-check",
        action="store_true",
        help="Skip the source freshness gate before running against the project DB",
    )
    args = parser.parse_args()

    run_experiment(
        db_path=args.db,
        ticker=args.ticker,
        source_table=args.source_table,
        train_start=args.train_start,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        test_start=args.test_start,
        test_end=args.test_end,
        output_table=args.output_table,
        metrics_json=args.metrics_json,
        embargo=args.embargo,
        embargo_unit=args.embargo_unit,
        skip_freshness_check=args.skip_freshness_check,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
