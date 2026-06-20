#!/usr/bin/env python3
"""Export row-level factor model scores for diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.bucket_ablation_harness import (  # noqa: E402
    features_for_bucket_stack,
)
from scripts.experiments.bucket_model_harness import (  # noqa: E402
    DEFAULT_BUCKETS,
    json_safe,
    load_factor_panel,
    parse_buckets,
)
from scripts.experiments.build_factor_targets import quote_identifier  # noqa: E402
from scripts.experiments.check_factor_dataset_quality import DEFAULT_TABLE  # noqa: E402
from scripts.experiments.factor_time_splits import make_factor_time_splits  # noqa: E402
from scripts.experiments.train_rsi_one_ticker_baselines import split_ranges  # noqa: E402


DEFAULT_OUTPUT_TABLE = "factor_smoke_scores_v1"
DEFAULT_SCORE_SPLITS = ("validation", "test")
OPTIONAL_DIAGNOSTIC_COLUMNS = (
    "sector",
    "risk_beta_spy_21d",
    "liq_adv_20d",
)


def parse_score_splits(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return DEFAULT_SCORE_SPLITS
    splits: list[str] = []
    for value in values:
        splits.extend(part.strip().lower() for part in value.split(","))
    allowed = {"train", "validation", "test"}
    selected = tuple(dict.fromkeys(split for split in splits if split))
    unsupported = sorted(set(selected) - allowed)
    if unsupported:
        raise ValueError(f"unsupported score split: {', '.join(unsupported)}")
    if not selected:
        raise ValueError("at least one score split is required")
    return selected


def score_split_rows(
    split_df: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    split_name: str,
    model: Ridge,
    optional_columns: tuple[str, ...] = OPTIONAL_DIAGNOSTIC_COLUMNS,
) -> pd.DataFrame:
    required_columns = ["ticker", "date"] + feature_columns + [target_column]
    complete = split_df.dropna(subset=required_columns).copy()
    if complete.empty:
        return pd.DataFrame()

    prior_column = target_column.replace("future_", "prior_")
    winner_column = target_column.replace("future_", "winner_").replace("_return", "")
    carry_columns = [
        column
        for column in (
            "ticker",
            "date",
            "panel_name",
            target_column,
            winner_column,
            prior_column,
            *optional_columns,
        )
        if column in complete.columns
    ]
    scored = complete[carry_columns].copy()
    scored["split"] = split_name
    scored["prediction_score"] = model.predict(complete[feature_columns])
    return scored


def write_score_table(
    conn: duckdb.DuckDBPyConnection,
    output_table: str,
    scored: pd.DataFrame,
) -> None:
    if scored.empty:
        raise ValueError("no scored rows to export")
    duplicate_count = int(scored.duplicated(["ticker", "date"]).sum())
    if duplicate_count:
        raise ValueError(f"duplicate scored ticker/date rows found: {duplicate_count}")

    conn.register("scored_factor_export", scored)
    try:
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS
            SELECT *
            FROM scored_factor_export
            ORDER BY date, ticker
            """
        )
    finally:
        conn.unregister("scored_factor_export")


def export_factor_scores(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    output_table: str = DEFAULT_OUTPUT_TABLE,
    bucket_stack: tuple[str, ...] = DEFAULT_BUCKETS,
    target_horizon: int = 21,
    train_end: str = "",
    validation_end: str = "",
    test_end: str = "",
    score_splits: tuple[str, ...] = DEFAULT_SCORE_SPLITS,
    tickers: list[str] | None = None,
    train_start: str | None = None,
    validation_start: str | None = None,
    test_start: str | None = None,
    embargo: int | None = None,
    embargo_unit: str = "trading",
    alpha: float = 1.0,
) -> dict[str, Any]:
    if target_horizon < 1:
        raise ValueError("target_horizon must be >= 1")
    if alpha < 0:
        raise ValueError("alpha must be >= 0")

    selected_buckets = parse_buckets(list(bucket_stack))
    selected_score_splits = parse_score_splits(list(score_splits))
    df = load_factor_panel(conn, table_name=table_name, tickers=tickers)
    target_column = f"future_{target_horizon}d_return"
    if target_column not in df.columns:
        raise ValueError(f"missing target column: {target_column}")

    feature_columns = features_for_bucket_stack(df, list(selected_buckets))
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
        prediction_horizon_days=target_horizon,
    )

    train_required = feature_columns + [target_column]
    train_complete = splits["train"].dropna(subset=train_required).copy()
    if train_complete.empty:
        raise ValueError("train split has no complete rows")

    model = Ridge(alpha=alpha)
    model.fit(train_complete[feature_columns], train_complete[target_column])

    scored_parts = [
        score_split_rows(
            splits[split_name],
            feature_columns=feature_columns,
            target_column=target_column,
            split_name=split_name,
            model=model,
        )
        for split_name in selected_score_splits
    ]
    scored = pd.concat(scored_parts, ignore_index=True) if scored_parts else pd.DataFrame()
    write_score_table(conn, output_table=output_table, scored=scored)

    split_counts = (
        scored.groupby("split").size().astype(int).to_dict()
        if "split" in scored.columns
        else {}
    )
    optional_columns = [
        column for column in OPTIONAL_DIAGNOSTIC_COLUMNS if column in scored.columns
    ]
    return {
        "mode": "factor_score_export",
        "source_table": table_name,
        "output_table": output_table,
        "bucket_stack": list(selected_buckets),
        "target": target_column,
        "model": "ridge_regression",
        "alpha": alpha,
        "feature_count": len(feature_columns),
        "feature_columns": feature_columns,
        "score_splits": list(selected_score_splits),
        "global_split_ranges": split_ranges(splits),
        "train_complete_rows": int(len(train_complete)),
        "scored_rows": int(len(scored)),
        "scored_split_counts": {str(key): int(value) for key, value in split_counts.items()},
        "optional_columns": optional_columns,
        "duplicate_key_count": int(scored.duplicated(["ticker", "date"]).sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export row-level factor model scores for diagnostics",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Factor panel table (default: {DEFAULT_TABLE})",
    )
    parser.add_argument(
        "--output-table",
        default=DEFAULT_OUTPUT_TABLE,
        help=f"Output score table (default: {DEFAULT_OUTPUT_TABLE})",
    )
    parser.add_argument(
        "--bucket-stack",
        nargs="*",
        default=list(DEFAULT_BUCKETS),
        help="Buckets to train, comma or space separated",
    )
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--target-horizon", type=int, default=21)
    parser.add_argument("--train-start", default=None)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--validation-start", default=None)
    parser.add_argument("--validation-end", required=True)
    parser.add_argument("--test-start", default=None)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--score-splits", nargs="*", default=list(DEFAULT_SCORE_SPLITS))
    parser.add_argument("--embargo", type=int, default=0)
    parser.add_argument("--embargo-unit", choices=("calendar", "trading"), default="trading")
    parser.add_argument("--alpha", type=float, default=1.0)
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        report = export_factor_scores(
            conn,
            table_name=args.table,
            output_table=args.output_table,
            bucket_stack=parse_buckets(args.bucket_stack),
            target_horizon=args.target_horizon,
            train_start=args.train_start,
            train_end=args.train_end,
            validation_start=args.validation_start,
            validation_end=args.validation_end,
            test_start=args.test_start,
            test_end=args.test_end,
            score_splits=parse_score_splits(args.score_splits),
            tickers=args.tickers,
            embargo=args.embargo,
            embargo_unit=args.embargo_unit,
            alpha=args.alpha,
        )
    finally:
        conn.close()

    print("Factor score export report")
    print(json.dumps(json_safe(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
