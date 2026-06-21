#!/usr/bin/env python3
"""Walk-forward evaluation driver for factor bucket models."""

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

from scripts.experiments.bucket_model_harness import (  # noqa: E402
    DEFAULT_BUCKETS,
    complete_split_rows,
    evaluate_bucket_regression,
    feature_policy_for_bucket_stack,
    json_safe,
    load_factor_panel,
    parse_buckets,
    run_bucket_only_models,
    select_feature_columns_for_policy,
    skipped_feature_policy_summary,
)
from scripts.experiments.check_factor_dataset_quality import DEFAULT_TABLE  # noqa: E402
from scripts.experiments.factor_neutrality_diagnostics import (  # noqa: E402
    DEFAULT_SECTOR_COLUMN,
    run_factor_neutrality_diagnostics,
)
from scripts.experiments.factor_time_splits import make_factor_time_splits  # noqa: E402
from scripts.experiments.train_rsi_one_ticker_baselines import split_ranges  # noqa: E402
from scripts.experiments.turnover_capacity_metrics import (  # noqa: E402
    DEFAULT_COST_BPS,
    DEFAULT_LIQUIDITY_COLUMN,
    run_turnover_capacity_metrics,
)


def date_string(value: object) -> str:
    return str(pd.Timestamp(value))[:10]


def make_walk_forward_folds(
    dates: pd.Series | list[object],
    train_size: int,
    validation_size: int,
    test_size: int,
    step_size: int | None = None,
    expanding: bool = False,
) -> list[dict[str, str]]:
    if train_size < 1 or validation_size < 1 or test_size < 1:
        raise ValueError("train_size, validation_size, and test_size must be >= 1")
    step = step_size or test_size
    if step < 1:
        raise ValueError("step_size must be >= 1")

    unique_dates = sorted(pd.to_datetime(pd.Series(dates).dropna().unique()))
    folds = []
    start = 0
    total_window = train_size + validation_size + test_size
    while start + total_window <= len(unique_dates):
        train_start_index = 0 if expanding else start
        train_end_index = start + train_size - 1
        validation_start_index = train_end_index + 1
        validation_end_index = validation_start_index + validation_size - 1
        test_start_index = validation_end_index + 1
        test_end_index = test_start_index + test_size - 1
        folds.append(
            {
                "train_start": date_string(unique_dates[train_start_index]),
                "train_end": date_string(unique_dates[train_end_index]),
                "validation_start": date_string(unique_dates[validation_start_index]),
                "validation_end": date_string(unique_dates[validation_end_index]),
                "test_start": date_string(unique_dates[test_start_index]),
                "test_end": date_string(unique_dates[test_end_index]),
            }
        )
        start += step
    if not folds:
        raise ValueError("not enough dates for requested walk-forward windows")
    return folds


def metric_or_nan(summary: dict[str, Any], bucket: str, split: str, metric: str) -> float:
    bucket_result = summary["buckets"].get(bucket, {})
    if bucket_result.get("status") != "computed" or "metrics" not in bucket_result:
        return float("nan")
    value = bucket_result["metrics"][split]["ranking"][metric]
    if value is None:
        return float("nan")
    return float(value)


def bucket_status_counts(
    fold_results: list[dict[str, Any]],
    bucket: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fold in fold_results:
        bucket_result = fold["summary"]["buckets"].get(bucket, {})
        status = str(bucket_result.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def aggregate_walk_forward_metrics(fold_results: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = fold_results[0]["summary"]["buckets"].keys()
    metrics = (
        "top_k_average_return",
        "top_k_win_rate",
        "mean_information_coefficient",
    )
    aggregate: dict[str, Any] = {}
    for bucket in buckets:
        aggregate[bucket] = {
            "status_counts": bucket_status_counts(fold_results, bucket),
        }
        for split in ("validation", "test"):
            aggregate[bucket][split] = {"fold_count": len(fold_results)}
            for metric in metrics:
                values = [
                    metric_or_nan(fold["summary"], bucket, split, metric)
                    for fold in fold_results
                ]
                numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
                aggregate[bucket][split][f"mean_{metric}"] = (
                    float(numeric.mean()) if not numeric.empty else math.nan
                )
                aggregate[bucket][split][f"non_null_{metric}_fold_count"] = int(
                    len(numeric)
                )
    return aggregate


def stack_metric_or_nan(
    summary: dict[str, Any],
    split: str,
    section: str,
    metric: str,
) -> float:
    stack = summary.get("stack", {})
    if stack.get("status") != "computed" or "metrics" not in stack:
        return float("nan")
    if section == "ranking":
        value = stack["metrics"][split]["ranking"][metric]
    elif section == "baseline_comparison":
        value = stack["metrics"][split]["baseline_comparison"][metric]
    else:
        raise ValueError(f"unsupported stack metric section: {section}")
    if value is None:
        return float("nan")
    return float(value)


def stack_status_counts(fold_results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fold in fold_results:
        stack_result = fold["summary"].get("stack", {})
        status = str(stack_result.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def aggregate_stack_walk_forward_metrics(
    fold_results: list[dict[str, Any]],
) -> dict[str, Any]:
    ranking_metrics = (
        "top_k_average_return",
        "top_k_win_rate",
        "mean_information_coefficient",
    )
    baseline_metrics = (
        "top_k_average_return_delta",
        "mean_information_coefficient_delta",
    )
    aggregate: dict[str, Any] = {"status_counts": stack_status_counts(fold_results)}
    for split in ("validation", "test"):
        aggregate[split] = {"fold_count": len(fold_results)}
        for metric in ranking_metrics:
            values = [
                stack_metric_or_nan(fold["summary"], split, "ranking", metric)
                for fold in fold_results
            ]
            numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
            aggregate[split][f"mean_{metric}"] = (
                float(numeric.mean()) if not numeric.empty else math.nan
            )
            aggregate[split][f"non_null_{metric}_fold_count"] = int(len(numeric))
        for metric in baseline_metrics:
            values = [
                stack_metric_or_nan(
                    fold["summary"],
                    split,
                    "baseline_comparison",
                    metric,
                )
                for fold in fold_results
            ]
            numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
            aggregate[split][f"mean_baseline_{metric}"] = (
                float(numeric.mean()) if not numeric.empty else math.nan
            )
            aggregate[split][
                f"non_null_baseline_{metric}_fold_count"
            ] = int(len(numeric))
    return aggregate


def diagnostic_metric_or_nan(
    summary: dict[str, Any],
    diagnostic_name: str,
    split: str,
    metric_path: tuple[str, ...],
) -> float:
    diagnostic = summary.get("diagnostics", {}).get(diagnostic_name, {})
    split_report = (
        diagnostic.get("split_summary", {})
        .get("splits", {})
        .get(split, {})
    )
    value: Any = split_report
    for key in metric_path:
        if not isinstance(value, dict) or key not in value:
            return float("nan")
        value = value[key]
    if value is None:
        return float("nan")
    return float(value)


def aggregate_stack_diagnostics(fold_results: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        "neutrality": {
            "beta_adjusted_top_k_average_return": (
                "beta_adjusted",
                "ranking",
                "top_k_average_return",
            ),
            "sector_neutral_top_k_average_return": (
                "sector",
                "sector_neutral",
                "top_k_average_return",
            ),
            "max_sector_share": (
                "sector",
                "top_k_concentration",
                "max_sector_share",
            ),
        },
        "turnover_capacity": {
            "average_turnover": ("average_turnover",),
            "cost_adjusted_top_k_average_return": (
                "cost_adjusted_top_k_average_return",
            ),
            "minimum_liquidity": (
                "liquidity_summary",
                "minimum_liquidity",
            ),
        },
    }
    aggregate: dict[str, Any] = {}
    for diagnostic_name, diagnostic_metrics in metrics.items():
        aggregate[diagnostic_name] = {}
        for split in ("validation", "test"):
            aggregate[diagnostic_name][split] = {}
            for metric_name, metric_path in diagnostic_metrics.items():
                values = [
                    diagnostic_metric_or_nan(
                        fold["summary"],
                        diagnostic_name,
                        split,
                        metric_path,
                    )
                    for fold in fold_results
                ]
                numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
                aggregate[diagnostic_name][split][f"mean_{metric_name}"] = (
                    float(numeric.mean()) if not numeric.empty else math.nan
                )
                aggregate[diagnostic_name][split][
                    f"non_null_{metric_name}_fold_count"
                ] = int(len(numeric))
    return aggregate


def scored_rows_for_stack(
    complete_splits: dict[str, pd.DataFrame],
    feature_columns: list[str],
    target_column: str,
    alpha: float,
) -> pd.DataFrame:
    model = Ridge(alpha=alpha)
    model.fit(
        complete_splits["train"][feature_columns],
        complete_splits["train"][target_column],
    )
    prior_column = target_column.replace("future_", "prior_")
    winner_column = target_column.replace("future_", "winner_").replace("_return", "")
    optional_columns = (
        "panel_name",
        winner_column,
        prior_column,
        DEFAULT_SECTOR_COLUMN,
        "industry",
        "risk_beta_spy_21d",
        DEFAULT_LIQUIDITY_COLUMN,
    )
    scored_parts = []
    for split_name in ("validation", "test"):
        split_df = complete_splits[split_name]
        carry_columns = [
            column
            for column in ("ticker", "date", target_column, *optional_columns)
            if column in split_df.columns
        ]
        scored = split_df[carry_columns].copy()
        scored["split"] = split_name
        scored["prediction_score"] = (
            model.predict(split_df[feature_columns])
            if not split_df.empty
            else pd.Series([], index=split_df.index, dtype="float64")
        )
        scored_parts.append(scored)
    return pd.concat(scored_parts, ignore_index=True)


def run_stack_diagnostics(
    scored: pd.DataFrame,
    target_column: str,
    top_k: int,
    cost_bps: float,
) -> dict[str, Any]:
    beta_column = "risk_beta_spy_21d" if "risk_beta_spy_21d" in scored.columns else None
    return {
        "neutrality": run_factor_neutrality_diagnostics(
            scored,
            score_column="prediction_score",
            target_column=target_column,
            beta_column=beta_column,
            top_k=top_k,
        ),
        "turnover_capacity": run_turnover_capacity_metrics(
            scored,
            score_column="prediction_score",
            target_column=target_column,
            liquidity_column=DEFAULT_LIQUIDITY_COLUMN,
            top_k=top_k,
            cost_bps=cost_bps,
        ),
    }


def run_bucket_stack_model(
    df: pd.DataFrame,
    table_name: str,
    buckets: tuple[str, ...],
    target_horizon: int,
    train_start: str,
    train_end: str,
    validation_start: str,
    validation_end: str,
    test_start: str,
    test_end: str,
    embargo: int | None,
    embargo_unit: str,
    top_k: int,
    alpha: float,
    cost_bps: float,
) -> dict[str, Any]:
    target_column = f"future_{target_horizon}d_return"
    prior_column = f"prior_{target_horizon}d_return"
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
    feature_policy = feature_policy_for_bucket_stack(df, list(buckets))
    try:
        features, policy_summary = select_feature_columns_for_policy(
            base_splits,
            feature_policy,
            target_column,
        )
        stack_result = evaluate_bucket_regression(
            base_splits,
            feature_columns=features,
            target_column=target_column,
            prior_column=prior_column if prior_column in df.columns else None,
            top_k=top_k,
            alpha=alpha,
        )
        complete_splits = complete_split_rows(
            base_splits,
            features + [target_column],
        )
        scored = scored_rows_for_stack(
            complete_splits,
            feature_columns=features,
            target_column=target_column,
            alpha=alpha,
        )
        stack_result["feature_policy"] = policy_summary
        stack_result["scored_rows"] = int(len(scored))
        diagnostics = run_stack_diagnostics(
            scored,
            target_column=target_column,
            top_k=top_k,
            cost_bps=cost_bps,
        )
    except ValueError as exc:
        policy_summary = skipped_feature_policy_summary(
            base_splits,
            feature_policy,
            target_column,
        )
        stack_result = {
            "status": "skipped",
            "reason": str(exc),
            "feature_columns": policy_summary["model_feature_columns"],
            "target": target_column,
            "complete_split_ranges": policy_summary[
                "required_complete_split_ranges"
            ],
            "feature_policy": policy_summary,
        }
        diagnostics = {}

    return {
        "mode": "bucket_stack",
        "table": table_name,
        "target": target_column,
        "bucket_stack": list(buckets),
        "global_split_ranges": split_ranges(base_splits),
        "embargo": embargo,
        "embargo_unit": embargo_unit,
        "top_k": top_k,
        "cost_bps": cost_bps,
        "stack": stack_result,
        "diagnostics": diagnostics,
    }


def run_walk_forward_factor_evaluation(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    buckets: tuple[str, ...] = DEFAULT_BUCKETS,
    evaluation_mode: str = "bucket_only",
    target_horizon: int = 21,
    train_size: int = 252,
    validation_size: int = 63,
    test_size: int = 63,
    step_size: int | None = None,
    expanding: bool = False,
    tickers: list[str] | None = None,
    embargo: int | None = 0,
    embargo_unit: str = "trading",
    top_k: int = 10,
    alpha: float = 1.0,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    selected_buckets = parse_buckets(list(buckets))
    if evaluation_mode not in {"bucket_only", "stack"}:
        raise ValueError("evaluation_mode must be bucket_only or stack")
    df = load_factor_panel(conn, table_name=table_name, tickers=tickers)
    folds = make_walk_forward_folds(
        df["date"],
        train_size=train_size,
        validation_size=validation_size,
        test_size=test_size,
        step_size=step_size,
        expanding=expanding,
    )

    fold_results = []
    for index, fold in enumerate(folds, start=1):
        if evaluation_mode == "bucket_only":
            summary = run_bucket_only_models(
                conn,
                table_name=table_name,
                buckets=selected_buckets,
                target_horizon=target_horizon,
                tickers=tickers,
                train_start=fold["train_start"],
                train_end=fold["train_end"],
                validation_start=fold["validation_start"],
                validation_end=fold["validation_end"],
                test_start=fold["test_start"],
                test_end=fold["test_end"],
                embargo=embargo,
                embargo_unit=embargo_unit,
                top_k=top_k,
                alpha=alpha,
            )
        else:
            summary = run_bucket_stack_model(
                df,
                table_name=table_name,
                buckets=selected_buckets,
                target_horizon=target_horizon,
                train_start=fold["train_start"],
                train_end=fold["train_end"],
                validation_start=fold["validation_start"],
                validation_end=fold["validation_end"],
                test_start=fold["test_start"],
                test_end=fold["test_end"],
                embargo=embargo,
                embargo_unit=embargo_unit,
                top_k=top_k,
                alpha=alpha,
                cost_bps=cost_bps,
            )
        fold_results.append({"fold": index, "ranges": fold, "summary": summary})

    report = {
        "mode": "walk_forward_factor_evaluation",
        "evaluation_mode": evaluation_mode,
        "table": table_name,
        "bucket_order": list(selected_buckets),
        "target_horizon": target_horizon,
        "fold_count": len(fold_results),
        "folds": fold_results,
    }
    if evaluation_mode == "bucket_only":
        report["aggregate_metrics"] = aggregate_walk_forward_metrics(fold_results)
    else:
        report["aggregate_metrics"] = aggregate_stack_walk_forward_metrics(fold_results)
        report["aggregate_diagnostics"] = aggregate_stack_diagnostics(fold_results)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run walk-forward factor bucket evaluations",
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
    parser.add_argument(
        "--evaluation-mode",
        choices=("bucket_only", "stack"),
        default="bucket_only",
        help="Evaluate buckets independently or as one combined stack",
    )
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--target-horizon", type=int, default=21)
    parser.add_argument("--train-size", type=int, required=True)
    parser.add_argument("--validation-size", type=int, required=True)
    parser.add_argument("--test-size", type=int, required=True)
    parser.add_argument("--step-size", type=int, default=None)
    parser.add_argument("--expanding", action="store_true")
    parser.add_argument("--embargo", type=int, default=0)
    parser.add_argument("--embargo-unit", choices=("calendar", "trading"), default="trading")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        report = run_walk_forward_factor_evaluation(
            conn,
            table_name=args.table,
            buckets=parse_buckets(args.buckets),
            evaluation_mode=args.evaluation_mode,
            target_horizon=args.target_horizon,
            train_size=args.train_size,
            validation_size=args.validation_size,
            test_size=args.test_size,
            step_size=args.step_size,
            expanding=args.expanding,
            tickers=args.tickers,
            embargo=args.embargo,
            embargo_unit=args.embargo_unit,
            top_k=args.top_k,
            alpha=args.alpha,
            cost_bps=args.cost_bps,
        )
    finally:
        conn.close()

    print("Walk-forward factor evaluation report")
    print(json.dumps(json_safe(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
