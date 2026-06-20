#!/usr/bin/env python3
"""Cumulative bucket ablation harness for factor panels."""

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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.bucket_model_harness import (  # noqa: E402
    DEFAULT_BUCKETS,
    complete_split_rows,
    evaluate_bucket_regression,
    json_safe,
    load_factor_panel,
    parse_buckets,
)
from scripts.experiments.check_factor_dataset_quality import (  # noqa: E402
    BUCKET_PREFIXES,
    DEFAULT_TABLE,
)
from scripts.experiments.factor_time_splits import make_factor_time_splits  # noqa: E402
from scripts.experiments.train_rsi_one_ticker_baselines import split_ranges  # noqa: E402


DEFAULT_MIN_VALIDATION_DELTA = 0.0
DEFAULT_ALLOWED_TEST_DEGRADATION = 0.0


def features_for_bucket_stack(df: pd.DataFrame, buckets: list[str]) -> list[str]:
    features: list[str] = []
    for bucket in buckets:
        prefix = BUCKET_PREFIXES[bucket]
        bucket_features = [column for column in df.columns if column.startswith(prefix)]
        if not bucket_features:
            raise ValueError(f"no feature columns found for bucket: {bucket}")
        features.extend(bucket_features)
    return list(dict.fromkeys(features))


def metric_at(result: dict[str, Any], split_name: str, metric_name: str) -> float:
    return float(result["metrics"][split_name]["ranking"][metric_name])


def safe_delta(left: float, right: float) -> float:
    if math.isnan(left) or math.isnan(right):
        return float("nan")
    return left - right


def comparison_deltas(
    candidate: dict[str, Any],
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    if prior is None:
        return {
            "validation_top_k_average_return_delta": None,
            "validation_mean_information_coefficient_delta": None,
            "test_top_k_average_return_delta": None,
            "test_mean_information_coefficient_delta": None,
            "test_degradation_visible": False,
        }

    validation_return_delta = safe_delta(
        metric_at(candidate, "validation", "top_k_average_return"),
        metric_at(prior, "validation", "top_k_average_return"),
    )
    validation_ic_delta = safe_delta(
        metric_at(candidate, "validation", "mean_information_coefficient"),
        metric_at(prior, "validation", "mean_information_coefficient"),
    )
    test_return_delta = safe_delta(
        metric_at(candidate, "test", "top_k_average_return"),
        metric_at(prior, "test", "top_k_average_return"),
    )
    test_ic_delta = safe_delta(
        metric_at(candidate, "test", "mean_information_coefficient"),
        metric_at(prior, "test", "mean_information_coefficient"),
    )
    return {
        "validation_top_k_average_return_delta": validation_return_delta,
        "validation_mean_information_coefficient_delta": validation_ic_delta,
        "test_top_k_average_return_delta": test_return_delta,
        "test_mean_information_coefficient_delta": test_ic_delta,
        "test_degradation_visible": (
            not math.isnan(test_return_delta) and test_return_delta < 0
        ),
    }


def should_keep_candidate(
    deltas: dict[str, Any],
    min_validation_delta: float = DEFAULT_MIN_VALIDATION_DELTA,
    allowed_test_degradation: float = DEFAULT_ALLOWED_TEST_DEGRADATION,
) -> bool:
    return (
        candidate_recommendation(
            deltas,
            min_validation_delta=min_validation_delta,
            allowed_test_degradation=allowed_test_degradation,
        )
        == "keep"
    )


def candidate_recommendation(
    deltas: dict[str, Any],
    min_validation_delta: float = DEFAULT_MIN_VALIDATION_DELTA,
    allowed_test_degradation: float = DEFAULT_ALLOWED_TEST_DEGRADATION,
) -> str:
    validation_delta = deltas["validation_top_k_average_return_delta"]
    test_delta = deltas["test_top_k_average_return_delta"]
    if validation_delta is None:
        return "keep"
    if math.isnan(validation_delta) or validation_delta <= min_validation_delta:
        return "reject"
    if test_delta is not None and not math.isnan(test_delta):
        if test_delta < -allowed_test_degradation:
            return "watch"
    return "keep"


def complete_split_ranges_for_columns(
    splits: dict[str, pd.DataFrame],
    required_columns: list[str],
) -> dict[str, dict[str, Any]]:
    complete_splits = {
        split_name: split_df.dropna(subset=required_columns).copy()
        for split_name, split_df in splits.items()
    }
    return split_ranges(complete_splits)


def evaluate_stack_pair(
    splits: dict[str, pd.DataFrame],
    candidate_features: list[str],
    target_column: str,
    prior_column: str | None,
    prior_features: list[str] | None = None,
    top_k: int = 10,
    alpha: float = 1.0,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, dict[str, Any]]]:
    comparison_features = list(dict.fromkeys((prior_features or []) + candidate_features))
    comparison_splits = complete_split_rows(
        splits,
        comparison_features + [target_column],
    )
    prior_result = None
    if prior_features:
        prior_result = evaluate_bucket_regression(
            comparison_splits,
            feature_columns=prior_features,
            target_column=target_column,
            prior_column=prior_column,
            top_k=top_k,
            alpha=alpha,
        )
    candidate_result = evaluate_bucket_regression(
        comparison_splits,
        feature_columns=candidate_features,
        target_column=target_column,
        prior_column=prior_column,
        top_k=top_k,
        alpha=alpha,
    )
    return prior_result, candidate_result, split_ranges(comparison_splits)


def run_cumulative_bucket_ablations(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    bucket_order: tuple[str, ...] = DEFAULT_BUCKETS,
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
    min_validation_delta: float = DEFAULT_MIN_VALIDATION_DELTA,
    allowed_test_degradation: float = DEFAULT_ALLOWED_TEST_DEGRADATION,
) -> dict[str, Any]:
    if target_horizon < 1:
        raise ValueError("target_horizon must be >= 1")
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if alpha < 0:
        raise ValueError("alpha must be >= 0")
    selected_buckets = parse_buckets(list(bucket_order))
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

    accepted_buckets: list[str] = []
    accepted_features: list[str] = []
    steps = []
    for bucket in selected_buckets:
        candidate_buckets = accepted_buckets + [bucket]
        candidate_features = features_for_bucket_stack(df, candidate_buckets)
        try:
            prior_result, candidate_result, comparison_ranges = evaluate_stack_pair(
                base_splits,
                candidate_features=candidate_features,
                prior_features=accepted_features or None,
                target_column=target_column,
                prior_column=prior_column if prior_column in df.columns else None,
                top_k=top_k,
                alpha=alpha,
            )
        except ValueError as exc:
            comparison_ranges = complete_split_ranges_for_columns(
                base_splits,
                candidate_features + [target_column],
            )
            steps.append(
                {
                    "bucket": bucket,
                    "candidate_stack": candidate_buckets,
                    "prior_accepted_stack": candidate_buckets[:-1],
                    "accepted_stack_after": accepted_buckets.copy(),
                    "candidate": {
                        "status": "skipped",
                        "reason": str(exc),
                        "feature_columns": candidate_features,
                        "target": target_column,
                        "complete_split_ranges": comparison_ranges,
                    },
                    "prior_comparison": None,
                    "comparison_split_ranges": comparison_ranges,
                    "deltas_vs_prior_accepted": {
                        "validation_top_k_average_return_delta": None,
                        "validation_mean_information_coefficient_delta": None,
                        "test_top_k_average_return_delta": None,
                        "test_mean_information_coefficient_delta": None,
                        "test_degradation_visible": False,
                    },
                    "keep": False,
                    "recommendation": "reject",
                }
            )
            continue
        deltas = comparison_deltas(candidate_result, prior_result)
        recommendation = candidate_recommendation(
            deltas,
            min_validation_delta=min_validation_delta,
            allowed_test_degradation=allowed_test_degradation,
        )
        keep = should_keep_candidate(
            deltas,
            min_validation_delta=min_validation_delta,
            allowed_test_degradation=allowed_test_degradation,
        )
        if keep:
            accepted_buckets = candidate_buckets
            accepted_features = candidate_features

        steps.append(
            {
                "bucket": bucket,
                "candidate_stack": candidate_buckets,
                "prior_accepted_stack": candidate_buckets[:-1],
                "accepted_stack_after": accepted_buckets.copy(),
                "candidate": candidate_result,
                "prior_comparison": prior_result,
                "comparison_split_ranges": comparison_ranges,
                "deltas_vs_prior_accepted": deltas,
                "keep": keep,
                "recommendation": recommendation,
            }
        )

    return {
        "mode": "cumulative_bucket_ablation",
        "table": table_name,
        "target": target_column,
        "bucket_order": list(selected_buckets),
        "accepted_buckets": accepted_buckets,
        "global_split_ranges": split_ranges(base_splits),
        "embargo": embargo,
        "embargo_unit": embargo_unit,
        "top_k": top_k,
        "steps": steps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run cumulative factor bucket ablations",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Factor panel table (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--bucket-order",
        nargs="*",
        default=list(DEFAULT_BUCKETS),
        help="Bucket order, comma or space separated",
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
    parser.add_argument("--min-validation-delta", type=float, default=0.0)
    parser.add_argument("--allowed-test-degradation", type=float, default=0.0)
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        summary = run_cumulative_bucket_ablations(
            conn,
            table_name=args.table,
            bucket_order=parse_buckets(args.bucket_order),
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
            min_validation_delta=args.min_validation_delta,
            allowed_test_degradation=args.allowed_test_degradation,
        )
    finally:
        conn.close()

    print("Cumulative bucket ablation report")
    print(json.dumps(json_safe(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
