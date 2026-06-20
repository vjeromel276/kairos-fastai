#!/usr/bin/env python3
"""Turnover, cost, and capacity proxy metrics for factor predictions."""

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

from scripts.experiments.build_factor_targets import quote_identifier  # noqa: E402
from scripts.experiments.check_factor_dataset_quality import DEFAULT_TABLE  # noqa: E402


DEFAULT_SCORE_COLUMN = "prediction_score"
DEFAULT_TARGET_COLUMN = "future_21d_return"
DEFAULT_LIQUIDITY_COLUMN = "liq_adv_20d"
DEFAULT_TOP_K = 10
DEFAULT_COST_BPS = 10.0


def load_scored_panel(
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
        ORDER BY date, ticker
        """
    ).fetchdf()


def require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")


def select_top_k_by_date(
    df: pd.DataFrame,
    score_column: str = DEFAULT_SCORE_COLUMN,
    date_column: str = "date",
    top_k: int = DEFAULT_TOP_K,
) -> tuple[pd.DataFrame, int]:
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    require_columns(df, (date_column, score_column))

    selected = []
    missing_score_days = 0
    for trading_date, group in df.groupby(date_column, sort=True):
        valid = group.dropna(subset=[score_column]).copy()
        if valid.empty:
            missing_score_days += 1
            continue
        ranked = valid.sort_values(score_column, ascending=False).head(top_k)
        ranked["selection_rank"] = range(1, len(ranked) + 1)
        ranked["selection_date"] = trading_date
        selected.append(ranked)

    if not selected:
        return df.iloc[0:0].copy(), missing_score_days
    return pd.concat(selected, ignore_index=True), missing_score_days


def liquidity_summary(
    selected: pd.DataFrame,
    liquidity_column: str = DEFAULT_LIQUIDITY_COLUMN,
) -> dict[str, Any]:
    if liquidity_column not in selected.columns:
        return {
            "status": "skipped",
            "reason": f"liquidity column missing: {liquidity_column}",
        }
    liquidity = pd.to_numeric(selected[liquidity_column], errors="coerce").dropna()
    if liquidity.empty:
        return {"status": "empty", "selected_count": len(selected)}
    return {
        "status": "computed",
        "selected_count": len(selected),
        "average_liquidity": float(liquidity.mean()),
        "median_liquidity": float(liquidity.median()),
        "minimum_liquidity": float(liquidity.min()),
    }


def turnover_rows(
    selected: pd.DataFrame,
    target_column: str = DEFAULT_TARGET_COLUMN,
    ticker_column: str = "ticker",
    date_column: str = "date",
    cost_bps: float = DEFAULT_COST_BPS,
) -> list[dict[str, Any]]:
    require_columns(selected, (date_column, ticker_column, target_column))
    if cost_bps < 0:
        raise ValueError("cost_bps must be >= 0")

    rows = []
    previous_holdings: set[str] | None = None
    cost_rate = cost_bps / 10_000.0
    for trading_date, group in selected.groupby(date_column, sort=True):
        holdings = set(group[ticker_column].dropna().astype(str))
        if previous_holdings is None:
            overlap = math.nan
            turnover = math.nan
            cost = 0.0
        else:
            denominator = max(len(previous_holdings), len(holdings), 1)
            overlap = len(previous_holdings & holdings) / denominator
            turnover = 1.0 - overlap
            cost = turnover * cost_rate

        gross_return = pd.to_numeric(group[target_column], errors="coerce").mean()
        cost_adjusted_return = gross_return - cost if not pd.isna(gross_return) else math.nan
        rows.append(
            {
                "date": trading_date,
                "selected_count": len(holdings),
                "holding_overlap": overlap,
                "turnover": turnover,
                "gross_return": float(gross_return) if not pd.isna(gross_return) else math.nan,
                "cost_bps": cost_bps,
                "transaction_cost": float(cost),
                "cost_adjusted_return": float(cost_adjusted_return)
                if not pd.isna(cost_adjusted_return)
                else math.nan,
            }
        )
        previous_holdings = holdings
    return rows


def average_non_null(values: list[object]) -> float:
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else math.nan


def run_turnover_capacity_metrics(
    df: pd.DataFrame,
    score_column: str = DEFAULT_SCORE_COLUMN,
    target_column: str = DEFAULT_TARGET_COLUMN,
    liquidity_column: str = DEFAULT_LIQUIDITY_COLUMN,
    ticker_column: str = "ticker",
    date_column: str = "date",
    top_k: int = DEFAULT_TOP_K,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    require_columns(df, (date_column, ticker_column, score_column, target_column))
    selected, missing_score_days = select_top_k_by_date(
        df,
        score_column=score_column,
        date_column=date_column,
        top_k=top_k,
    )
    rows = turnover_rows(
        selected,
        target_column=target_column,
        ticker_column=ticker_column,
        date_column=date_column,
        cost_bps=cost_bps,
    )
    return {
        "row_count": len(df),
        "top_k": top_k,
        "score_column": score_column,
        "target_column": target_column,
        "selected_date_count": int(selected[date_column].nunique()) if not selected.empty else 0,
        "missing_score_date_count": missing_score_days,
        "turnover_by_date": rows,
        "average_turnover": average_non_null([row["turnover"] for row in rows]),
        "average_holding_overlap": average_non_null(
            [row["holding_overlap"] for row in rows]
        ),
        "gross_top_k_average_return": average_non_null(
            [row["gross_return"] for row in rows]
        ),
        "cost_adjusted_top_k_average_return": average_non_null(
            [row["cost_adjusted_return"] for row in rows]
        ),
        "liquidity_summary": liquidity_summary(
            selected,
            liquidity_column=liquidity_column,
        ),
    }


def validate_turnover_capacity(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    score_column: str = DEFAULT_SCORE_COLUMN,
    target_column: str = DEFAULT_TARGET_COLUMN,
    liquidity_column: str = DEFAULT_LIQUIDITY_COLUMN,
    ticker_column: str = "ticker",
    date_column: str = "date",
    top_k: int = DEFAULT_TOP_K,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict[str, Any]:
    df = load_scored_panel(conn, table_name=table_name)
    report = run_turnover_capacity_metrics(
        df,
        score_column=score_column,
        target_column=target_column,
        liquidity_column=liquidity_column,
        ticker_column=ticker_column,
        date_column=date_column,
        top_k=top_k,
        cost_bps=cost_bps,
    )
    report["table"] = table_name
    return report


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
        description="Run turnover, cost, and capacity proxy metrics",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Scored panel table (default: {DEFAULT_TABLE})",
    )
    parser.add_argument("--score-column", default=DEFAULT_SCORE_COLUMN)
    parser.add_argument("--target-column", default=DEFAULT_TARGET_COLUMN)
    parser.add_argument("--liquidity-column", default=DEFAULT_LIQUIDITY_COLUMN)
    parser.add_argument("--ticker-column", default="ticker")
    parser.add_argument("--date-column", default="date")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        report = validate_turnover_capacity(
            conn,
            table_name=args.table,
            score_column=args.score_column,
            target_column=args.target_column,
            liquidity_column=args.liquidity_column,
            ticker_column=args.ticker_column,
            date_column=args.date_column,
            top_k=args.top_k,
            cost_bps=args.cost_bps,
        )
    finally:
        conn.close()

    print("Turnover and capacity metrics report")
    print(json.dumps(json_safe(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
