#!/usr/bin/env python3
"""Train one-ticker RSI-today baseline models."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.build_rsi_one_ticker_dataset import (  # noqa: E402
    DEFAULT_OUTPUT_TABLE,
    quote_identifier,
)
from scripts.experiments.rsi_metrics import (  # noqa: E402
    always_up_baseline,
    classification_metrics,
    mean_return_baseline,
    prior_return_baseline,
    regression_metrics,
)
from scripts.experiments.rsi_time_splits import make_time_splits  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_FEATURE_COLUMN = "rsi_14"
DEFAULT_RETURN_TARGET = "future_5d_return"
DEFAULT_DIRECTION_TARGET = "winner_5d"
DEFAULT_PRIOR_HORIZON_DAYS = 5


def load_one_ticker_dataset(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    ticker: str,
) -> pd.DataFrame:
    table_identifier = quote_identifier(table_name)
    query = f"""
        SELECT *
        FROM {table_identifier}
        WHERE ticker = ?
        ORDER BY date
    """
    df = conn.execute(query, [ticker]).fetchdf()
    if df.empty:
        raise ValueError(f"no rows found for ticker {ticker} in {table_name}")
    return df


def complete_rows(
    df: pd.DataFrame,
    required_columns: list[str],
) -> pd.DataFrame:
    missing = sorted(set(required_columns) - set(df.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    return df.dropna(subset=required_columns).copy()


def split_ranges(splits: dict[str, pd.DataFrame]) -> dict[str, dict[str, str | int | None]]:
    ranges: dict[str, dict[str, str | int | None]] = {}
    for split_name, split_df in splits.items():
        if split_df.empty:
            ranges[split_name] = {"rows": 0, "min_date": None, "max_date": None}
            continue
        ranges[split_name] = {
            "rows": len(split_df),
            "min_date": str(split_df["date"].min())[:10],
            "max_date": str(split_df["date"].max())[:10],
        }
    return ranges


def split_complete_rows(
    df: pd.DataFrame,
    train_end: str,
    validation_end: str,
    test_end: str,
    train_start: str | None = None,
    validation_start: str | None = None,
    test_start: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
) -> dict[str, pd.DataFrame]:
    splits = make_time_splits(
        df,
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=test_end,
        embargo=embargo,
        embargo_unit=embargo_unit,
    )
    if splits["train"].empty:
        raise ValueError("train split has no complete rows")
    return splits


def prior_direction_baseline(prior_returns: pd.Series) -> pd.Series:
    prediction = pd.Series(np.nan, index=prior_returns.index, dtype="float64")
    prediction.loc[prior_returns.notna()] = (prior_returns.loc[prior_returns.notna()] > 0).astype(
        "float64"
    )
    return prediction


def evaluate_regression(
    df: pd.DataFrame,
    feature_column: str,
    target_column: str,
    train_end: str,
    validation_end: str,
    test_end: str,
    train_start: str | None = None,
    validation_start: str | None = None,
    test_start: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
) -> dict[str, Any]:
    model_df = complete_rows(df, [feature_column, target_column]).copy()
    splits = split_complete_rows(
        model_df,
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=test_end,
        embargo=embargo,
        embargo_unit=embargo_unit,
    )

    model = LinearRegression()
    model.fit(splits["train"][[feature_column]], splits["train"][target_column])

    evaluations: dict[str, Any] = {}
    for split_name in ("validation", "test"):
        split_df = splits[split_name]
        model_prediction = pd.Series(
            model.predict(split_df[[feature_column]]) if not split_df.empty else [],
            index=split_df.index,
            dtype="float64",
        )
        mean_prediction = mean_return_baseline(splits["train"][target_column], split_df.index)
        evaluations[split_name] = {
            "model": regression_metrics(split_df[target_column], model_prediction),
            "mean_return_baseline": regression_metrics(split_df[target_column], mean_prediction),
            "prior_return_baseline": regression_metrics(
                split_df[target_column],
                split_df["prior_5d_return"],
            ),
        }

    return {
        "model": "linear_regression",
        "feature_columns": [feature_column],
        "target": target_column,
        "split_ranges": split_ranges(splits),
        "prediction_counts": {
            "train": 0,
            "validation": len(splits["validation"]),
            "test": len(splits["test"]),
        },
        "metrics": evaluations,
    }


def evaluate_classification(
    df: pd.DataFrame,
    feature_column: str,
    target_column: str,
    train_end: str,
    validation_end: str,
    test_end: str,
    train_start: str | None = None,
    validation_start: str | None = None,
    test_start: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
) -> dict[str, Any]:
    model_df = complete_rows(df, [feature_column, target_column]).copy()
    splits = split_complete_rows(
        model_df,
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=test_end,
        embargo=embargo,
        embargo_unit=embargo_unit,
    )
    if splits["train"][target_column].nunique() < 2:
        raise ValueError("classification train split must contain both classes")

    model = LogisticRegression(max_iter=1000)
    model.fit(splits["train"][[feature_column]], splits["train"][target_column].astype("int64"))

    evaluations: dict[str, Any] = {}
    for split_name in ("validation", "test"):
        split_df = splits[split_name]
        if split_df.empty:
            model_prediction = pd.Series([], index=split_df.index, dtype="float64")
        else:
            model_prediction = pd.Series(
                model.predict_proba(split_df[[feature_column]])[:, 1],
                index=split_df.index,
                dtype="float64",
            )
        evaluations[split_name] = {
            "model": classification_metrics(split_df[target_column], model_prediction),
            "always_up_baseline": classification_metrics(
                split_df[target_column],
                always_up_baseline(split_df.index),
            ),
            "prior_return_direction_baseline": classification_metrics(
                split_df[target_column],
                split_df["prior_5d_direction"],
            ),
        }

    return {
        "model": "logistic_regression",
        "feature_columns": [feature_column],
        "target": target_column,
        "split_ranges": split_ranges(splits),
        "prediction_counts": {
            "train": 0,
            "validation": len(splits["validation"]),
            "test": len(splits["test"]),
        },
        "metrics": evaluations,
    }


def run_one_ticker_baselines(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    table_name: str = DEFAULT_OUTPUT_TABLE,
    feature_column: str = DEFAULT_FEATURE_COLUMN,
    return_target: str = DEFAULT_RETURN_TARGET,
    direction_target: str = DEFAULT_DIRECTION_TARGET,
    train_end: str = "",
    validation_end: str = "",
    test_end: str = "",
    train_start: str | None = None,
    validation_start: str | None = None,
    test_start: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
    prior_horizon_days: int = DEFAULT_PRIOR_HORIZON_DAYS,
) -> dict[str, Any]:
    df = load_one_ticker_dataset(conn, table_name=table_name, ticker=ticker)
    df["prior_5d_return"] = prior_return_baseline(
        df["closeadj"],
        horizon_days=prior_horizon_days,
    )
    df["prior_5d_direction"] = prior_direction_baseline(df["prior_5d_return"])

    common_kwargs = {
        "feature_column": feature_column,
        "train_start": train_start,
        "train_end": train_end,
        "validation_start": validation_start,
        "validation_end": validation_end,
        "test_start": test_start,
        "test_end": test_end,
        "embargo": embargo,
        "embargo_unit": embargo_unit,
    }
    return {
        "ticker": ticker,
        "table": table_name,
        "regression": evaluate_regression(
            df,
            target_column=return_target,
            **common_kwargs,
        ),
        "classification": evaluate_classification(
            df,
            target_column=direction_target,
            **common_kwargs,
        ),
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
    if isinstance(value, float):
        return None if math.isnan(value) else value
    return value


def write_metrics_json(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(json_safe(summary), f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def print_summary(summary: dict[str, Any]) -> None:
    print(f"Ticker: {summary['ticker']}")
    for model_key in ("regression", "classification"):
        model_summary = summary[model_key]
        print(f"{model_key}: {model_summary['model']} on {model_summary['feature_columns']}")
        for split_name in ("validation", "test"):
            metrics = model_summary["metrics"][split_name]["model"]
            print(f"  {split_name}: {metrics}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train one-ticker RSI-today baseline models",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument("--ticker", required=True, help="Ticker to train, for example AAPL")
    parser.add_argument(
        "--table",
        default=DEFAULT_OUTPUT_TABLE,
        help=f"RSI experiment table to read (default: {DEFAULT_OUTPUT_TABLE})",
    )
    parser.add_argument("--train-start", default=None, help="Optional train start date")
    parser.add_argument("--train-end", required=True, help="Train window end date")
    parser.add_argument("--validation-start", default=None, help="Optional validation start date")
    parser.add_argument("--validation-end", required=True, help="Validation window end date")
    parser.add_argument("--test-start", default=None, help="Optional test start date")
    parser.add_argument("--test-end", required=True, help="Test window end date")
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
        "--metrics-json",
        type=Path,
        default=None,
        help="Optional path to write JSON metrics summary",
    )
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        summary = run_one_ticker_baselines(
            conn,
            ticker=args.ticker,
            table_name=args.table,
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

    print_summary(summary)
    if args.metrics_json:
        write_metrics_json(summary, args.metrics_json)
        logger.info("Wrote metrics JSON to %s", args.metrics_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
