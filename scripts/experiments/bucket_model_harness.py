#!/usr/bin/env python3
"""Bucket-only diagnostic model harness for factor panels."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.build_factor_targets import quote_identifier  # noqa: E402
from scripts.experiments.check_factor_dataset_quality import (  # noqa: E402
    BUCKET_PREFIXES,
    DEFAULT_TABLE,
)
from scripts.experiments.factor_time_splits import make_factor_time_splits  # noqa: E402
from scripts.experiments.rsi_metrics import regression_metrics  # noqa: E402
from scripts.experiments.train_rsi_one_ticker_baselines import (  # noqa: E402
    ranking_metrics_by_date,
    split_ranges,
)


BUCKET_ALIASES = {
    "price": "price_behavior",
    "price_behavior": "price_behavior",
    "cross_sectional": "cross_sectional_context",
    "cross_sectional_context": "cross_sectional_context",
    "volume": "volume_liquidity",
    "volume_liquidity": "volume_liquidity",
    "liquidity": "volume_liquidity",
    "volatility": "volatility_risk",
    "volatility_risk": "volatility_risk",
    "risk": "volatility_risk",
    "fundamental": "fundamental_quality",
    "fundamental_quality": "fundamental_quality",
    "quality": "fundamental_quality",
    "valuation": "valuation",
    "regime": "regime_context",
    "regime_context": "regime_context",
}
DEFAULT_BUCKETS = (
    "price_behavior",
    "cross_sectional_context",
    "volume_liquidity",
    "volatility_risk",
    "fundamental_quality",
    "valuation",
    "regime_context",
)


def normalize_bucket(bucket: str) -> str:
    normalized = bucket.strip().lower().replace("-", "_")
    if normalized not in BUCKET_ALIASES:
        raise ValueError(f"unsupported bucket: {bucket}")
    return BUCKET_ALIASES[normalized]


def parse_buckets(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return DEFAULT_BUCKETS
    buckets: list[str] = []
    for value in values:
        buckets.extend(part.strip() for part in value.split(","))
    return tuple(dict.fromkeys(normalize_bucket(bucket) for bucket in buckets if bucket))


def load_factor_panel(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    tickers: list[str] | None = None,
) -> pd.DataFrame:
    table_identifier = quote_identifier(table_name)
    params: list[object] = []
    ticker_filter = ""
    if tickers:
        selected = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
        if not selected:
            raise ValueError("at least one ticker is required")
        placeholders = ", ".join(["?"] * len(selected))
        ticker_filter = f"WHERE ticker IN ({placeholders})"
        params.extend(selected)

    query = f"""
        SELECT *
        FROM {table_identifier}
        {ticker_filter}
        ORDER BY date, ticker
    """
    df = conn.execute(query, params).fetchdf()
    if df.empty:
        raise ValueError(f"no rows found in {table_name}")
    duplicate_count = int(df.duplicated(["ticker", "date"]).sum())
    if duplicate_count:
        raise ValueError(f"duplicate ticker/date rows found: {duplicate_count}")
    return df


def bucket_feature_columns(df: pd.DataFrame, bucket: str) -> list[str]:
    bucket_name = normalize_bucket(bucket)
    prefix = BUCKET_PREFIXES[bucket_name]
    columns = [column for column in df.columns if column.startswith(prefix)]
    if not columns:
        raise ValueError(f"no feature columns found for bucket: {bucket_name}")
    return columns


def complete_split_rows(
    splits: dict[str, pd.DataFrame],
    required_columns: list[str],
) -> dict[str, pd.DataFrame]:
    complete: dict[str, pd.DataFrame] = {}
    for split_name, split_df in splits.items():
        complete[split_name] = split_df.dropna(subset=required_columns).copy()
    if complete["train"].empty:
        raise ValueError("train split has no complete rows")
    return complete


def nan_delta(left: object, right: object) -> float:
    left_value = float(left)
    right_value = float(right)
    if math.isnan(left_value) or math.isnan(right_value):
        return float("nan")
    return left_value - right_value


def evaluate_bucket_regression(
    splits: dict[str, pd.DataFrame],
    feature_columns: list[str],
    target_column: str,
    prior_column: str | None,
    top_k: int = 10,
    alpha: float = 1.0,
) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if alpha < 0:
        raise ValueError("alpha must be >= 0")

    required_columns = feature_columns + [target_column]
    complete_splits = complete_split_rows(splits, required_columns)
    model = Ridge(alpha=alpha)
    model.fit(
        complete_splits["train"][feature_columns],
        complete_splits["train"][target_column],
    )

    evaluations: dict[str, Any] = {}
    for split_name in ("validation", "test"):
        split_df = complete_splits[split_name]
        if split_df.empty:
            model_prediction = pd.Series([], index=split_df.index, dtype="float64")
        else:
            model_prediction = pd.Series(
                model.predict(split_df[feature_columns]),
                index=split_df.index,
                dtype="float64",
            )

        if prior_column and prior_column in split_df.columns:
            baseline_prediction = pd.to_numeric(split_df[prior_column], errors="coerce")
            baseline_name = prior_column
        else:
            mean_target = complete_splits["train"][target_column].mean()
            baseline_prediction = pd.Series(
                mean_target,
                index=split_df.index,
                dtype="float64",
            )
            baseline_name = "train_mean_return"

        model_ranking = ranking_metrics_by_date(
            split_df[target_column],
            model_prediction,
            split_df["date"],
            top_k=top_k,
        )
        baseline_ranking = ranking_metrics_by_date(
            split_df[target_column],
            baseline_prediction,
            split_df["date"],
            top_k=top_k,
        )
        evaluations[split_name] = {
            "model": regression_metrics(split_df[target_column], model_prediction),
            "ranking": model_ranking,
            "baseline": baseline_name,
            "baseline_ranking": baseline_ranking,
            "baseline_comparison": {
                "top_k_average_return_delta": nan_delta(
                    model_ranking["top_k_average_return"],
                    baseline_ranking["top_k_average_return"],
                ),
                "mean_information_coefficient_delta": nan_delta(
                    model_ranking["mean_information_coefficient"],
                    baseline_ranking["mean_information_coefficient"],
                ),
            },
        }

    return {
        "model": "ridge_regression",
        "alpha": alpha,
        "feature_columns": feature_columns,
        "target": target_column,
        "complete_split_ranges": split_ranges(complete_splits),
        "metrics": evaluations,
    }


def run_bucket_only_models(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    buckets: tuple[str, ...] = DEFAULT_BUCKETS,
    target_horizon: int = 21,
    train_end: str = "",
    validation_end: str = "",
    test_end: str = "",
    tickers: list[str] | None = None,
    train_start: str | None = None,
    validation_start: str | None = None,
    test_start: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
    top_k: int = 10,
    alpha: float = 1.0,
) -> dict[str, Any]:
    if target_horizon < 1:
        raise ValueError("target_horizon must be >= 1")
    selected_buckets = parse_buckets(list(buckets))
    df = load_factor_panel(conn, table_name=table_name, tickers=tickers)
    target_column = f"future_{target_horizon}d_return"
    prior_column = f"prior_{target_horizon}d_return"
    if target_column not in df.columns:
        raise ValueError(f"missing target column: {target_column}")

    base_splits = make_factor_time_splits(
        df,
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=test_end,
        embargo=embargo,
        embargo_unit=embargo_unit,
        prediction_horizon_days=target_horizon,
    )
    global_split_ranges = split_ranges(base_splits)
    results = {}
    for bucket in selected_buckets:
        features = bucket_feature_columns(df, bucket)
        results[bucket] = evaluate_bucket_regression(
            base_splits,
            feature_columns=features,
            target_column=target_column,
            prior_column=prior_column if prior_column in df.columns else None,
            top_k=top_k,
            alpha=alpha,
        )

    return {
        "mode": "bucket_only",
        "table": table_name,
        "target": target_column,
        "tickers": sorted(df["ticker"].dropna().unique().tolist()),
        "buckets": results,
        "global_split_ranges": global_split_ranges,
        "embargo": embargo,
        "embargo_unit": embargo_unit,
        "top_k": top_k,
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return str(value)[:10]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bucket-only factor panel diagnostic models",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Factor panel table (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--buckets",
        nargs="*",
        default=list(DEFAULT_BUCKETS),
        help="Buckets to evaluate, comma or space separated",
    )
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--target-horizon", type=int, default=21)
    parser.add_argument("--train-start", default=None)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--validation-start", default=None)
    parser.add_argument("--validation-end", required=True)
    parser.add_argument("--test-start", default=None)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--embargo", type=int, default=0)
    parser.add_argument("--embargo-unit", choices=("calendar", "trading"), default="trading")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--alpha", type=float, default=1.0)
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        summary = run_bucket_only_models(
            conn,
            table_name=args.table,
            buckets=parse_buckets(args.buckets),
            target_horizon=args.target_horizon,
            train_start=args.train_start,
            train_end=args.train_end,
            validation_start=args.validation_start,
            validation_end=args.validation_end,
            test_start=args.test_start,
            test_end=args.test_end,
            tickers=args.tickers,
            embargo=args.embargo,
            embargo_unit=args.embargo_unit,
            top_k=args.top_k,
            alpha=args.alpha,
        )
    finally:
        conn.close()

    print("Bucket-only factor model report")
    print(json.dumps(json_safe(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
