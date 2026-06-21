#!/usr/bin/env python3
"""Read-only quality checks for multi-factor experiment datasets."""

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

from scripts.experiments.factor_feature_policy import (  # noqa: E402
    OPTIONAL_FEATURES_BY_BUCKET,
)
from scripts.experiments.factor_time_splits import make_factor_time_splits  # noqa: E402


DEFAULT_TABLE = "factor_panel_v1"
DEFAULT_TARGET_HORIZONS = (21, 5)
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEY_COLUMNS = {"ticker", "date"}
BASE_COLUMNS = {
    "ticker",
    "date",
    "panel_name",
    "prior_21d_return",
    "prior_5d_return",
    "dollar_volume",
    "adv_20",
    "adv_60",
    "exchange",
    "sector",
    "industry",
    "is_large_cap_smoke",
}
BUCKET_PREFIXES = {
    "price_behavior": "px_",
    "cross_sectional_context": "xs_",
    "volume_liquidity": "liq_",
    "volatility_risk": "risk_",
    "fundamental_quality": "qual_",
    "valuation": "val_",
    "regime_context": "regime_",
    "legacy_rsi": "rsi_",
}


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"invalid DuckDB identifier: {identifier}")
    return f'"{identifier}"'


def target_columns(target_horizons: tuple[int, ...]) -> set[str]:
    columns: set[str] = set()
    for horizon in target_horizons:
        columns.add(f"future_{horizon}d_return")
        columns.add(f"winner_{horizon}d")
    return columns


def required_columns(target_horizons: tuple[int, ...]) -> set[str]:
    return KEY_COLUMNS | {"panel_name"} | target_columns(target_horizons)


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


def null_key_counts(df: pd.DataFrame) -> dict[str, int]:
    return {
        "null_ticker_rows": int(df["ticker"].isna().sum()),
        "null_date_rows": int(df["date"].isna().sum()),
    }


def model_feature_columns(
    df: pd.DataFrame,
    target_horizons: tuple[int, ...],
) -> list[str]:
    non_feature_columns = BASE_COLUMNS | target_columns(target_horizons)
    return [
        column
        for column in df.columns
        if column not in non_feature_columns
        and any(column.startswith(prefix) for prefix in BUCKET_PREFIXES.values())
    ]


def unclassified_columns(
    df: pd.DataFrame,
    target_horizons: tuple[int, ...],
) -> list[str]:
    known_columns = BASE_COLUMNS | target_columns(target_horizons)
    return [
        column
        for column in df.columns
        if column not in known_columns
        and not any(column.startswith(prefix) for prefix in BUCKET_PREFIXES.values())
    ]


def feature_null_counts(feature_df: pd.DataFrame) -> dict[str, int]:
    return {column: int(feature_df[column].isna().sum()) for column in feature_df.columns}


def bucket_availability(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    availability: dict[str, dict[str, Any]] = {}
    for bucket, prefix in BUCKET_PREFIXES.items():
        columns = [column for column in df.columns if column.startswith(prefix)]
        if not columns:
            availability[bucket] = {
                "column_count": 0,
                "columns": [],
                "rows_with_any_value": 0,
                "rows_with_all_values": 0,
                "total_null_values": 0,
            }
            continue

        bucket_df = df[columns]
        availability[bucket] = {
            "column_count": len(columns),
            "columns": columns,
            "rows_with_any_value": int(bucket_df.notna().any(axis=1).sum()),
            "rows_with_all_values": int(bucket_df.notna().all(axis=1).sum()),
            "total_null_values": int(bucket_df.isna().sum().sum()),
        }
    return availability


def optional_feature_quality_status(
    df: pd.DataFrame,
    column: str,
) -> dict[str, Any]:
    if column not in df.columns:
        return {
            "role": "optional",
            "status": "missing",
            "rows": len(df),
            "non_null_rows": 0,
            "null_rows": len(df),
            "reason": "optional feature column missing",
        }

    non_null_rows = int(df[column].notna().sum())
    row_count = int(len(df))
    null_rows = row_count - non_null_rows
    if non_null_rows == 0:
        status = "skipped"
        reason = "optional feature all null"
    elif null_rows:
        status = "partial"
        reason = "optional feature has missing values"
    else:
        status = "computed"
        reason = "optional feature fully populated"
    return {
        "role": "optional",
        "status": status,
        "rows": row_count,
        "non_null_rows": non_null_rows,
        "null_rows": null_rows,
        "reason": reason,
    }


def feature_policy_availability(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    availability: dict[str, dict[str, Any]] = {}
    for bucket, optional_features in OPTIONAL_FEATURES_BY_BUCKET.items():
        prefix = BUCKET_PREFIXES[bucket]
        bucket_columns = [column for column in df.columns if column.startswith(prefix)]
        required_columns = [
            column for column in bucket_columns if column not in optional_features
        ]
        availability[bucket] = {
            "required_columns": required_columns,
            "optional_columns": sorted(optional_features),
            "optional_feature_status": {
                column: optional_feature_quality_status(df, column)
                for column in sorted(optional_features)
            },
        }
    return availability


def bucket_split_availability(
    splits: dict[str, pd.DataFrame],
    primary_target_column: str,
) -> dict[str, dict[str, Any]]:
    availability: dict[str, dict[str, Any]] = {}
    for bucket, prefix in BUCKET_PREFIXES.items():
        bucket_report = {}
        for split_name, split_df in splits.items():
            columns = [column for column in split_df.columns if column.startswith(prefix)]
            if not columns:
                bucket_report[split_name] = {
                    "row_count": len(split_df),
                    "column_count": 0,
                    "rows_with_any_value": 0,
                    "rows_with_all_values": 0,
                    "rows_with_all_values_and_primary_target": 0,
                }
                continue

            bucket_df = split_df[columns]
            all_features = bucket_df.notna().all(axis=1)
            if primary_target_column in split_df.columns:
                primary_target_available = split_df[primary_target_column].notna()
            else:
                primary_target_available = pd.Series(False, index=split_df.index)
            bucket_report[split_name] = {
                "row_count": len(split_df),
                "column_count": len(columns),
                "rows_with_any_value": int(bucket_df.notna().any(axis=1).sum()),
                "rows_with_all_values": int(all_features.sum()),
                "rows_with_all_values_and_primary_target": int(
                    (all_features & primary_target_available).sum()
                ),
            }
        availability[bucket] = bucket_report
    return availability


def target_availability_counts(
    df: pd.DataFrame,
    target_horizons: tuple[int, ...],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for horizon in target_horizons:
        target_column = f"future_{horizon}d_return"
        winner_column = f"winner_{horizon}d"
        target_available = df[target_column].notna()
        winner_available = df[winner_column].notna()
        winner_values = pd.to_numeric(df[winner_column], errors="coerce")

        counts[str(horizon)] = {
            "target_available_rows": int(target_available.sum()),
            "target_null_rows": int(target_available.size - target_available.sum()),
            "winner_available_rows": int(winner_available.sum()),
            "winner_null_rows": int(winner_available.size - winner_available.sum()),
            "unexpected_winner_nulls": int((target_available & ~winner_available).sum()),
            "unexpected_winner_values": int((~target_available & winner_available).sum()),
            "invalid_winner_values": int(
                (winner_available & ~winner_values.isin([0, 1])).sum()
            ),
        }
    return counts


def target_counts_valid(target_counts: dict[str, dict[str, int]]) -> bool:
    for counts in target_counts.values():
        if counts["unexpected_winner_nulls"]:
            return False
        if counts["unexpected_winner_values"]:
            return False
        if counts["invalid_winner_values"]:
            return False
    return True


def validate_factor_dataset_quality(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    target_horizons: tuple[int, ...] = DEFAULT_TARGET_HORIZONS,
    train_start: str | None = None,
    train_end: str | None = None,
    validation_start: str | None = None,
    validation_end: str | None = None,
    test_start: str | None = None,
    test_end: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
) -> dict[str, Any]:
    if not target_horizons:
        raise ValueError("at least one target horizon is required")
    if any(horizon < 1 for horizon in target_horizons):
        raise ValueError("target horizons must be >= 1")
    split_args = (train_start, train_end, validation_start, validation_end, test_start, test_end)
    if any(value is not None for value in split_args) and not (
        train_end and validation_end and test_end
    ):
        raise ValueError("train_end, validation_end, and test_end are required for split coverage")

    df = load_dataset(conn, table_name=table_name)
    missing_columns = sorted(required_columns(target_horizons) - set(df.columns))

    report: dict[str, Any] = {
        "table": table_name,
        "row_count": len(df),
        "ticker_count": int(df["ticker"].nunique()) if "ticker" in df.columns else 0,
        "panel_count": int(df["panel_name"].nunique()) if "panel_name" in df.columns else 0,
        "min_date": df["date"].min() if "date" in df.columns and not df.empty else None,
        "max_date": df["date"].max() if "date" in df.columns and not df.empty else None,
        "missing_columns": missing_columns,
        "null_key_counts": {},
        "duplicate_key_count": 0,
        "feature_null_counts": {},
        "bucket_availability": {},
        "feature_policy_availability": {},
        "bucket_split_availability": {},
        "target_availability": {},
        "unclassified_columns": [],
        "valid": False,
    }

    if missing_columns:
        return report

    feature_columns = model_feature_columns(df, target_horizons=target_horizons)
    report["null_key_counts"] = null_key_counts(df)
    report["duplicate_key_count"] = duplicate_key_count(df)
    report["feature_null_counts"] = feature_null_counts(df[feature_columns])
    report["bucket_availability"] = bucket_availability(df)
    report["feature_policy_availability"] = feature_policy_availability(df)
    if train_end and validation_end and test_end:
        splits = make_factor_time_splits(
            df,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            test_start=test_start,
            test_end=test_end,
            embargo=embargo,
            embargo_unit=embargo_unit,
            prediction_horizon_days=target_horizons[0],
        )
        report["bucket_split_availability"] = bucket_split_availability(
            splits,
            primary_target_column=f"future_{target_horizons[0]}d_return",
        )
    report["target_availability"] = target_availability_counts(
        df,
        target_horizons=target_horizons,
    )
    report["unclassified_columns"] = unclassified_columns(
        df,
        target_horizons=target_horizons,
    )

    report["valid"] = (
        report["duplicate_key_count"] == 0
        and report["null_key_counts"]["null_ticker_rows"] == 0
        and report["null_key_counts"]["null_date_rows"] == 0
        and target_counts_valid(report["target_availability"])
    )
    return report


def print_report(report: dict[str, Any]) -> None:
    print(f"Factor dataset quality report: {report['table']}")
    print(f"Rows: {report['row_count']:,}")
    print(f"Tickers: {report['ticker_count']:,}")
    print(f"Panels: {report['panel_count']:,}")
    print(f"Date range: {report['min_date']} -> {report['max_date']}")

    if report["missing_columns"]:
        print(f"Missing columns: {', '.join(report['missing_columns'])}")

    print(f"Duplicate ticker/date keys: {report['duplicate_key_count']}")
    if report["null_key_counts"]:
        print("Null key counts:")
        for key, value in report["null_key_counts"].items():
            print(f"  {key}: {value:,}")

    print("Feature null counts:")
    for column, null_count in report["feature_null_counts"].items():
        print(f"  {column}: {null_count:,}")

    print("Bucket availability:")
    for bucket, availability in report["bucket_availability"].items():
        print(
            f"  {bucket}: columns={availability['column_count']}, "
            f"rows_any={availability['rows_with_any_value']:,}, "
            f"rows_all={availability['rows_with_all_values']:,}, "
            f"null_values={availability['total_null_values']:,}"
        )

    if report["feature_policy_availability"]:
        print("Feature policy availability:")
        for bucket, policy in report["feature_policy_availability"].items():
            print(f"  {bucket}:")
            for column, status in policy["optional_feature_status"].items():
                print(
                    f"    optional {column}: status={status['status']}, "
                    f"non_null_rows={status['non_null_rows']:,}, "
                    f"null_rows={status['null_rows']:,}, "
                    f"reason={status['reason']}"
                )

    if report["bucket_split_availability"]:
        print("Bucket split availability:")
        for bucket, splits in report["bucket_split_availability"].items():
            print(f"  {bucket}:")
            for split_name, availability in splits.items():
                print(
                    f"    {split_name}: rows={availability['row_count']:,}, "
                    f"columns={availability['column_count']}, "
                    f"rows_any={availability['rows_with_any_value']:,}, "
                    f"rows_all={availability['rows_with_all_values']:,}, "
                    "rows_all_with_primary_target="
                    f"{availability['rows_with_all_values_and_primary_target']:,}"
                )

    if report["target_availability"]:
        print("Target availability:")
        for horizon, counts in report["target_availability"].items():
            print(f"  horizon_{horizon}d:")
            for key, value in counts.items():
                print(f"    {key}: {value:,}")

    if report["unclassified_columns"]:
        print(f"Unclassified columns: {', '.join(report['unclassified_columns'])}")

    print(f"Valid: {report['valid']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check multi-factor experiment dataset quality",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Factor experiment table to check (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--target-horizons",
        type=int,
        nargs="+",
        default=list(DEFAULT_TARGET_HORIZONS),
        help="Target horizons in trading rows (default: 21 5)",
    )
    parser.add_argument("--train-start", default=None)
    parser.add_argument("--train-end", default=None)
    parser.add_argument("--validation-start", default=None)
    parser.add_argument("--validation-end", default=None)
    parser.add_argument("--test-start", default=None)
    parser.add_argument("--test-end", default=None)
    parser.add_argument("--embargo", type=int, default=None)
    parser.add_argument("--embargo-unit", choices=("calendar", "trading"), default="trading")
    args = parser.parse_args()

    conn = duckdb.connect(args.db, read_only=True)
    try:
        report = validate_factor_dataset_quality(
            conn,
            table_name=args.table,
            target_horizons=tuple(args.target_horizons),
            train_start=args.train_start,
            train_end=args.train_end,
            validation_start=args.validation_start,
            validation_end=args.validation_end,
            test_start=args.test_start,
            test_end=args.test_end,
            embargo=args.embargo,
            embargo_unit=args.embargo_unit,
        )
    finally:
        conn.close()

    print_report(report)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
