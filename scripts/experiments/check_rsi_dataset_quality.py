#!/usr/bin/env python3
"""Read-only quality checks for RSI experiment datasets."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_TABLE = "rsi_experiment_one_ticker_v1"
DEFAULT_HORIZON_DAYS = 5
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BASE_COLUMNS = {"ticker", "date", "closeadj"}


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"invalid DuckDB identifier: {identifier}")
    return f'"{identifier}"'


def load_dataset(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
) -> pd.DataFrame:
    table_identifier = quote_identifier(table_name)
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    if table_name not in tables:
        raise ValueError(f"table does not exist: {table_name}")

    return conn.execute(
        f"""
        SELECT *
        FROM {table_identifier}
        ORDER BY ticker, date
        """
    ).fetchdf()


def duplicate_key_count(df: pd.DataFrame) -> int:
    duplicate_groups = (
        df.groupby(["ticker", "date"], dropna=False)
        .size()
        .reset_index(name="row_count")
    )
    return int((duplicate_groups["row_count"] > 1).sum())


def feature_columns(df: pd.DataFrame, horizon_days: int) -> list[str]:
    target_columns = {
        f"future_{horizon_days}d_return",
        f"winner_{horizon_days}d",
    }
    return [
        column
        for column in df.columns
        if column not in BASE_COLUMNS and column not in target_columns
    ]


def target_alignment_counts(df: pd.DataFrame, horizon_days: int) -> dict[str, int]:
    target_column = f"future_{horizon_days}d_return"
    winner_column = f"winner_{horizon_days}d"

    expected_available = (
        df.groupby("ticker", group_keys=False)["closeadj"]
        .apply(lambda close: close.notna() & close.shift(-horizon_days).notna())
        .sort_index()
    )
    target_available = df[target_column].notna()
    winner_available = df[winner_column].notna() if winner_column in df.columns else target_available

    return {
        "target_available_rows": int(target_available.sum()),
        "target_null_rows": int(target_available.size - target_available.sum()),
        "expected_target_available_rows": int(expected_available.sum()),
        "expected_target_null_rows": int(expected_available.size - expected_available.sum()),
        "unexpected_target_nulls": int((expected_available & ~target_available).sum()),
        "unexpected_target_values": int((~expected_available & target_available).sum()),
        "unexpected_winner_nulls": int((expected_available & ~winner_available).sum()),
        "unexpected_winner_values": int((~expected_available & winner_available).sum()),
    }


def validate_dataset_quality(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> dict[str, Any]:
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")

    df = load_dataset(conn, table_name=table_name)
    target_column = f"future_{horizon_days}d_return"
    winner_column = f"winner_{horizon_days}d"
    required_columns = BASE_COLUMNS | {target_column, winner_column}
    missing_columns = sorted(required_columns - set(df.columns))

    report: dict[str, Any] = {
        "table": table_name,
        "row_count": len(df),
        "ticker_count": int(df["ticker"].nunique()) if "ticker" in df.columns else 0,
        "min_date": df["date"].min() if "date" in df.columns and not df.empty else None,
        "max_date": df["date"].max() if "date" in df.columns and not df.empty else None,
        "missing_columns": missing_columns,
        "duplicate_key_count": 0,
        "feature_null_counts": {},
        "target_alignment": {},
        "valid": False,
    }

    if missing_columns:
        return report

    report["duplicate_key_count"] = duplicate_key_count(df)
    report["feature_null_counts"] = {
        column: int(df[column].isna().sum())
        for column in feature_columns(df, horizon_days=horizon_days)
    }
    report["target_alignment"] = target_alignment_counts(df, horizon_days=horizon_days)

    alignment = report["target_alignment"]
    report["valid"] = (
        report["duplicate_key_count"] == 0
        and alignment["unexpected_target_nulls"] == 0
        and alignment["unexpected_target_values"] == 0
        and alignment["unexpected_winner_nulls"] == 0
        and alignment["unexpected_winner_values"] == 0
    )
    return report


def print_report(report: dict[str, Any]) -> None:
    print(f"RSI dataset quality report: {report['table']}")
    print(f"Rows: {report['row_count']:,}")
    print(f"Tickers: {report['ticker_count']:,}")
    print(f"Date range: {report['min_date']} -> {report['max_date']}")

    if report["missing_columns"]:
        print(f"Missing columns: {', '.join(report['missing_columns'])}")

    print(f"Duplicate ticker/date keys: {report['duplicate_key_count']}")

    print("Feature null counts:")
    for column, null_count in report["feature_null_counts"].items():
        print(f"  {column}: {null_count:,}")

    if report["target_alignment"]:
        print("Target availability:")
        for key, value in report["target_alignment"].items():
            print(f"  {key}: {value:,}")

    print(f"Valid: {report['valid']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check RSI experiment dataset quality and target alignment",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"RSI experiment table to check (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=DEFAULT_HORIZON_DAYS,
        help=f"Future return horizon in trading rows (default: {DEFAULT_HORIZON_DAYS})",
    )
    args = parser.parse_args()

    conn = duckdb.connect(args.db, read_only=True)
    try:
        report = validate_dataset_quality(
            conn,
            table_name=args.table,
            horizon_days=args.horizon_days,
        )
    finally:
        conn.close()

    print_report(report)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
