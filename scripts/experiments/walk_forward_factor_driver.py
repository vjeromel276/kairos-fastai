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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.bucket_model_harness import (  # noqa: E402
    DEFAULT_BUCKETS,
    json_safe,
    load_factor_panel,
    parse_buckets,
    run_bucket_only_models,
)
from scripts.experiments.check_factor_dataset_quality import DEFAULT_TABLE  # noqa: E402


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
    value = summary["buckets"][bucket]["metrics"][split]["ranking"][metric]
    return float(value)


def aggregate_walk_forward_metrics(fold_results: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = fold_results[0]["summary"]["buckets"].keys()
    metrics = (
        "top_k_average_return",
        "top_k_win_rate",
        "mean_information_coefficient",
    )
    aggregate: dict[str, Any] = {}
    for bucket in buckets:
        aggregate[bucket] = {}
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
    return aggregate


def run_walk_forward_factor_evaluation(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    buckets: tuple[str, ...] = DEFAULT_BUCKETS,
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
) -> dict[str, Any]:
    selected_buckets = parse_buckets(list(buckets))
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
        fold_results.append({"fold": index, "ranges": fold, "summary": summary})

    return {
        "mode": "walk_forward_factor_evaluation",
        "table": table_name,
        "bucket_order": list(selected_buckets),
        "target_horizon": target_horizon,
        "fold_count": len(fold_results),
        "folds": fold_results,
        "aggregate_metrics": aggregate_walk_forward_metrics(fold_results),
    }


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
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        report = run_walk_forward_factor_evaluation(
            conn,
            table_name=args.table,
            buckets=parse_buckets(args.buckets),
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
        )
    finally:
        conn.close()

    print("Walk-forward factor evaluation report")
    print(json.dumps(json_safe(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
