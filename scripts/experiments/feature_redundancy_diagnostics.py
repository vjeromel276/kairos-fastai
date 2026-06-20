#!/usr/bin/env python3
"""Read-only redundancy diagnostics for factor feature panels."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.check_factor_dataset_quality import (  # noqa: E402
    BUCKET_PREFIXES,
    DEFAULT_TABLE,
    model_feature_columns,
    quote_identifier,
)


DEFAULT_HIGH_CORRELATION_THRESHOLD = 0.98
DEFAULT_NEAR_CONSTANT_VARIANCE_THRESHOLD = 1e-12
DEFAULT_MISSINGNESS_OVERLAP_THRESHOLD = 0.80


def feature_bucket(feature_name: str) -> str:
    for bucket, prefix in BUCKET_PREFIXES.items():
        if feature_name.startswith(prefix):
            return bucket
    return "unclassified"


def load_feature_dataset(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
) -> pd.DataFrame:
    tables = conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    if table_name not in tables:
        raise ValueError(f"table does not exist: {table_name}")
    return conn.execute(
        f"""
        SELECT *
        FROM {quote_identifier(table_name)}
        """
    ).fetchdf()


def selected_feature_columns(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
) -> list[str]:
    if feature_columns:
        missing = sorted(set(feature_columns) - set(df.columns))
        if missing:
            raise ValueError(f"missing feature columns: {', '.join(missing)}")
        return feature_columns
    return model_feature_columns(df, target_horizons=(21, 5))


def near_constant_features(
    feature_df: pd.DataFrame,
    variance_threshold: float = DEFAULT_NEAR_CONSTANT_VARIANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    if variance_threshold < 0:
        raise ValueError("variance_threshold must be >= 0")

    findings: list[dict[str, Any]] = []
    for column in feature_df.columns:
        series = pd.to_numeric(feature_df[column], errors="coerce")
        non_null_count = int(series.notna().sum())
        unique_count = int(series.dropna().nunique())
        variance = series.var(ddof=0)
        variance_value = None if pd.isna(variance) else float(variance)

        reason = None
        if non_null_count == 0:
            reason = "all_null"
        elif unique_count <= 1:
            reason = "single_value"
        elif variance_value is not None and variance_value <= variance_threshold:
            reason = "low_variance"

        if reason:
            findings.append(
                {
                    "feature": column,
                    "bucket": feature_bucket(column),
                    "reason": reason,
                    "non_null_count": non_null_count,
                    "unique_count": unique_count,
                    "variance": variance_value,
                }
            )
    return findings


def high_correlation_pairs(
    feature_df: pd.DataFrame,
    threshold: float = DEFAULT_HIGH_CORRELATION_THRESHOLD,
) -> list[dict[str, Any]]:
    if not 0 <= threshold <= 1:
        raise ValueError("correlation threshold must satisfy 0 <= threshold <= 1")

    numeric_df = feature_df.apply(pd.to_numeric, errors="coerce")
    correlation = numeric_df.corr()
    findings: list[dict[str, Any]] = []
    columns = list(correlation.columns)
    for left_index, left in enumerate(columns):
        for right in columns[left_index + 1 :]:
            value = correlation.loc[left, right]
            if pd.isna(value) or abs(value) < threshold:
                continue
            findings.append(
                {
                    "feature_a": left,
                    "feature_b": right,
                    "bucket_a": feature_bucket(left),
                    "bucket_b": feature_bucket(right),
                    "correlation": float(value),
                    "abs_correlation": float(abs(value)),
                }
            )
    return sorted(findings, key=lambda item: item["abs_correlation"], reverse=True)


def bucket_correlation_summary(feature_df: pd.DataFrame) -> list[dict[str, Any]]:
    numeric_df = feature_df.apply(pd.to_numeric, errors="coerce")
    correlation = numeric_df.corr()
    columns = list(correlation.columns)
    grouped: dict[tuple[str, str], list[float]] = {}
    for left_index, left in enumerate(columns):
        for right in columns[left_index + 1 :]:
            value = correlation.loc[left, right]
            if pd.isna(value):
                continue
            buckets = tuple(sorted((feature_bucket(left), feature_bucket(right))))
            grouped.setdefault(buckets, []).append(float(abs(value)))

    summary = []
    for (bucket_a, bucket_b), values in sorted(grouped.items()):
        summary.append(
            {
                "bucket_a": bucket_a,
                "bucket_b": bucket_b,
                "pair_count": len(values),
                "max_abs_correlation": max(values),
                "mean_abs_correlation": sum(values) / len(values),
            }
        )
    return summary


def missingness_report(feature_df: pd.DataFrame) -> list[dict[str, Any]]:
    row_count = len(feature_df)
    return [
        {
            "feature": column,
            "bucket": feature_bucket(column),
            "null_count": int(feature_df[column].isna().sum()),
            "null_rate": 0.0
            if row_count == 0
            else float(feature_df[column].isna().sum() / row_count),
        }
        for column in feature_df.columns
    ]


def missingness_overlap_pairs(
    feature_df: pd.DataFrame,
    threshold: float = DEFAULT_MISSINGNESS_OVERLAP_THRESHOLD,
) -> list[dict[str, Any]]:
    if not 0 <= threshold <= 1:
        raise ValueError("missingness threshold must satisfy 0 <= threshold <= 1")

    row_count = len(feature_df)
    findings: list[dict[str, Any]] = []
    columns = list(feature_df.columns)
    for left_index, left in enumerate(columns):
        for right in columns[left_index + 1 :]:
            both_null_count = int((feature_df[left].isna() & feature_df[right].isna()).sum())
            both_null_rate = 0.0 if row_count == 0 else both_null_count / row_count
            if both_null_rate < threshold:
                continue
            findings.append(
                {
                    "feature_a": left,
                    "feature_b": right,
                    "both_null_count": both_null_count,
                    "both_null_rate": float(both_null_rate),
                }
            )
    return sorted(findings, key=lambda item: item["both_null_rate"], reverse=True)


def run_feature_redundancy_diagnostics(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
    high_correlation_threshold: float = DEFAULT_HIGH_CORRELATION_THRESHOLD,
    near_constant_variance_threshold: float = DEFAULT_NEAR_CONSTANT_VARIANCE_THRESHOLD,
    missingness_overlap_threshold: float = DEFAULT_MISSINGNESS_OVERLAP_THRESHOLD,
) -> dict[str, Any]:
    columns = selected_feature_columns(df, feature_columns=feature_columns)
    feature_df = df[columns].copy()
    return {
        "row_count": len(df),
        "feature_count": len(columns),
        "feature_columns": columns,
        "near_constant_features": near_constant_features(
            feature_df,
            variance_threshold=near_constant_variance_threshold,
        ),
        "high_correlation_pairs": high_correlation_pairs(
            feature_df,
            threshold=high_correlation_threshold,
        ),
        "bucket_correlation_summary": bucket_correlation_summary(feature_df),
        "missingness": missingness_report(feature_df),
        "missingness_overlap_pairs": missingness_overlap_pairs(
            feature_df,
            threshold=missingness_overlap_threshold,
        ),
    }


def validate_feature_redundancy(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    feature_columns: list[str] | None = None,
    high_correlation_threshold: float = DEFAULT_HIGH_CORRELATION_THRESHOLD,
    near_constant_variance_threshold: float = DEFAULT_NEAR_CONSTANT_VARIANCE_THRESHOLD,
    missingness_overlap_threshold: float = DEFAULT_MISSINGNESS_OVERLAP_THRESHOLD,
) -> dict[str, Any]:
    df = load_feature_dataset(conn, table_name=table_name)
    report = run_feature_redundancy_diagnostics(
        df,
        feature_columns=feature_columns,
        high_correlation_threshold=high_correlation_threshold,
        near_constant_variance_threshold=near_constant_variance_threshold,
        missingness_overlap_threshold=missingness_overlap_threshold,
    )
    report["table"] = table_name
    return report


def print_report(report: dict[str, Any]) -> None:
    print(f"Feature redundancy report: {report.get('table', '<dataframe>')}")
    print(f"Rows: {report['row_count']}")
    print(f"Features: {report['feature_count']}")
    print(f"Near-constant features: {len(report['near_constant_features'])}")
    for item in report["near_constant_features"]:
        print(
            "  - "
            f"{item['feature']} ({item['reason']}, "
            f"non_null={item['non_null_count']}, unique={item['unique_count']})"
        )

    print(f"High-correlation pairs: {len(report['high_correlation_pairs'])}")
    for item in report["high_correlation_pairs"][:20]:
        print(
            "  - "
            f"{item['feature_a']} vs {item['feature_b']}: "
            f"{item['correlation']:.4f}"
        )

    print(f"Missingness overlap pairs: {len(report['missingness_overlap_pairs'])}")
    for item in report["missingness_overlap_pairs"][:20]:
        print(
            "  - "
            f"{item['feature_a']} vs {item['feature_b']}: "
            f"{item['both_null_rate']:.2%}"
        )

    print("Bucket correlation summary:")
    for item in report["bucket_correlation_summary"]:
        print(
            "  - "
            f"{item['bucket_a']} / {item['bucket_b']}: "
            f"pairs={item['pair_count']}, "
            f"max_abs={item['max_abs_correlation']:.4f}, "
            f"mean_abs={item['mean_abs_correlation']:.4f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run read-only factor feature redundancy diagnostics",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Factor panel table to inspect (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--feature-columns",
        nargs="*",
        default=None,
        help="Optional explicit feature columns; defaults to known factor prefixes",
    )
    parser.add_argument(
        "--high-correlation-threshold",
        type=float,
        default=DEFAULT_HIGH_CORRELATION_THRESHOLD,
    )
    parser.add_argument(
        "--near-constant-variance-threshold",
        type=float,
        default=DEFAULT_NEAR_CONSTANT_VARIANCE_THRESHOLD,
    )
    parser.add_argument(
        "--missingness-overlap-threshold",
        type=float,
        default=DEFAULT_MISSINGNESS_OVERLAP_THRESHOLD,
    )
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        report = validate_feature_redundancy(
            conn,
            table_name=args.table,
            feature_columns=args.feature_columns,
            high_correlation_threshold=args.high_correlation_threshold,
            near_constant_variance_threshold=args.near_constant_variance_threshold,
            missingness_overlap_threshold=args.missingness_overlap_threshold,
        )
    finally:
        conn.close()

    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
