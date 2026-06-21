#!/usr/bin/env python3
"""Sector-neutral and beta-adjusted ranking diagnostics for factor panels."""

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
from scripts.experiments.train_rsi_one_ticker_baselines import (  # noqa: E402
    ranking_metrics_by_date,
)


DEFAULT_SCORE_COLUMN = "prediction_score"
DEFAULT_TARGET_COLUMN = "future_21d_return"
DEFAULT_SECTOR_COLUMN = "sector"
DEFAULT_SPLIT_COLUMN = "split"
DEFAULT_TOP_K = 10


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


def top_k_sector_concentration(
    df: pd.DataFrame,
    score_column: str,
    sector_column: str,
    date_column: str = "date",
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    picks = []
    for _, group in df.dropna(subset=[score_column, sector_column]).groupby(date_column):
        picks.append(group.sort_values(score_column, ascending=False).head(top_k))
    if not picks:
        return {"status": "empty", "sector_pick_counts": {}, "max_sector_share": math.nan}

    selected = pd.concat(picks, ignore_index=True)
    counts = selected[sector_column].value_counts(dropna=False)
    total = int(counts.sum())
    shares = (counts / total).to_dict()
    return {
        "status": "computed",
        "selected_count": total,
        "sector_pick_counts": {str(key): int(value) for key, value in counts.items()},
        "sector_pick_shares": {str(key): float(value) for key, value in shares.items()},
        "max_sector_share": float(max(shares.values())) if shares else math.nan,
    }


def sector_neutral_ranking_metrics(
    df: pd.DataFrame,
    target_column: str,
    score_column: str,
    sector_column: str = DEFAULT_SECTOR_COLUMN,
    date_column: str = "date",
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, Any]:
    frame = df[[date_column, sector_column, target_column, score_column]].copy()
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
    frame[target_column] = pd.to_numeric(frame[target_column], errors="coerce")
    frame[score_column] = pd.to_numeric(frame[score_column], errors="coerce")
    frame = frame.dropna(subset=[date_column, sector_column, target_column, score_column])
    if frame.empty:
        return {
            "status": "empty",
            "date_count": 0,
            "sector_count": 0,
            "top_k_per_sector": top_k,
            "top_k_average_return": math.nan,
            "top_k_win_rate": math.nan,
            "mean_information_coefficient": math.nan,
        }

    selected_returns: list[float] = []
    selected_win_rates: list[float] = []
    information_coefficients: list[float] = []
    for _, group in frame.groupby([date_column, sector_column]):
        ranked = group.sort_values(score_column, ascending=False).head(top_k)
        selected_returns.append(float(ranked[target_column].mean()))
        selected_win_rates.append(float((ranked[target_column] > 0).mean()))
        if group[score_column].nunique() >= 2 and group[target_column].nunique() >= 2:
            information_coefficients.append(
                float(group[score_column].corr(group[target_column], method="spearman"))
            )

    return {
        "status": "computed",
        "date_count": int(frame[date_column].nunique()),
        "sector_count": int(frame[sector_column].nunique()),
        "top_k_per_sector": top_k,
        "top_k_average_return": float(np.mean(selected_returns)),
        "top_k_win_rate": float(np.mean(selected_win_rates)),
        "mean_information_coefficient": (
            float(np.mean(information_coefficients))
            if information_coefficients
            else math.nan
        ),
    }


def sector_breakdown(
    df: pd.DataFrame,
    target_column: str,
    score_column: str,
    sector_column: str,
    date_column: str = "date",
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, dict[str, Any]]:
    breakdown = {}
    for sector, group in df.dropna(subset=[sector_column]).groupby(sector_column):
        breakdown[str(sector)] = ranking_metrics_by_date(
            group[target_column],
            group[score_column],
            group[date_column],
            top_k=top_k,
        )
    return breakdown


def beta_adjust_scores_by_date(
    df: pd.DataFrame,
    score_column: str,
    beta_column: str,
    date_column: str = "date",
) -> pd.Series:
    require_columns(df, (date_column, score_column, beta_column))
    adjusted = pd.Series(float("nan"), index=df.index, dtype="float64")
    for _, group in df.groupby(date_column):
        scores = pd.to_numeric(group[score_column], errors="coerce")
        beta = pd.to_numeric(group[beta_column], errors="coerce")
        valid = scores.notna() & beta.notna()
        if valid.sum() < 2 or beta.loc[valid].var(ddof=0) == 0:
            adjusted.loc[group.index[valid]] = scores.loc[valid]
            continue
        slope = scores.loc[valid].cov(beta.loc[valid]) / beta.loc[valid].var()
        adjusted.loc[group.index[valid]] = scores.loc[valid] - slope * beta.loc[valid]
    return adjusted


def split_neutrality_summary(
    df: pd.DataFrame,
    split_column: str,
    score_column: str,
    target_column: str,
    date_column: str,
    sector_column: str,
    beta_column: str | None,
    top_k: int,
) -> dict[str, Any]:
    if split_column not in df.columns:
        return {
            "status": "skipped",
            "reason": f"split column missing: {split_column}",
        }

    frame = df.dropna(subset=[split_column])
    if frame.empty:
        return {
            "status": "empty",
            "split_column": split_column,
            "splits": {},
        }

    summaries = {}
    for split_name, split_df in frame.groupby(split_column, sort=True):
        summaries[str(split_name)] = run_factor_neutrality_diagnostics(
            split_df,
            score_column=score_column,
            target_column=target_column,
            date_column=date_column,
            sector_column=sector_column,
            beta_column=beta_column,
            top_k=top_k,
            split_column=None,
        )
    return {
        "status": "computed",
        "split_column": split_column,
        "splits": summaries,
    }


def run_factor_neutrality_diagnostics(
    df: pd.DataFrame,
    score_column: str = DEFAULT_SCORE_COLUMN,
    target_column: str = DEFAULT_TARGET_COLUMN,
    date_column: str = "date",
    sector_column: str = DEFAULT_SECTOR_COLUMN,
    beta_column: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    split_column: str | None = DEFAULT_SPLIT_COLUMN,
) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    require_columns(df, (date_column, target_column, score_column))

    full_panel = ranking_metrics_by_date(
        df[target_column],
        df[score_column],
        df[date_column],
        top_k=top_k,
    )
    if sector_column not in df.columns:
        sector = {
            "status": "skipped",
            "reason": f"sector column missing: {sector_column}",
        }
    else:
        sector = {
            "status": "computed",
            "sector_neutral": sector_neutral_ranking_metrics(
                df,
                target_column=target_column,
                score_column=score_column,
                sector_column=sector_column,
                date_column=date_column,
                top_k=top_k,
            ),
            "sector_breakdown": sector_breakdown(
                df,
                target_column=target_column,
                score_column=score_column,
                sector_column=sector_column,
                date_column=date_column,
                top_k=top_k,
            ),
            "top_k_concentration": top_k_sector_concentration(
                df,
                score_column=score_column,
                sector_column=sector_column,
                date_column=date_column,
                top_k=top_k,
            ),
        }

    if beta_column is None or beta_column not in df.columns:
        beta_adjusted = {
            "status": "skipped",
            "reason": "beta column not provided or missing",
        }
    else:
        adjusted_score = beta_adjust_scores_by_date(
            df,
            score_column=score_column,
            beta_column=beta_column,
            date_column=date_column,
        )
        beta_adjusted = {
            "status": "computed",
            "beta_column": beta_column,
            "ranking": ranking_metrics_by_date(
                df[target_column],
                adjusted_score,
                df[date_column],
                top_k=top_k,
            ),
        }

    report = {
        "row_count": len(df),
        "score_column": score_column,
        "target_column": target_column,
        "top_k": top_k,
        "full_panel": full_panel,
        "sector": sector,
        "beta_adjusted": beta_adjusted,
    }
    if split_column is not None:
        report["split_summary"] = split_neutrality_summary(
            df,
            split_column=split_column,
            score_column=score_column,
            target_column=target_column,
            date_column=date_column,
            sector_column=sector_column,
            beta_column=beta_column,
            top_k=top_k,
        )
    return report


def validate_factor_neutrality(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = DEFAULT_TABLE,
    score_column: str = DEFAULT_SCORE_COLUMN,
    target_column: str = DEFAULT_TARGET_COLUMN,
    date_column: str = "date",
    sector_column: str = DEFAULT_SECTOR_COLUMN,
    beta_column: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    split_column: str | None = DEFAULT_SPLIT_COLUMN,
) -> dict[str, Any]:
    df = load_scored_panel(conn, table_name=table_name)
    report = run_factor_neutrality_diagnostics(
        df,
        score_column=score_column,
        target_column=target_column,
        date_column=date_column,
        sector_column=sector_column,
        beta_column=beta_column,
        top_k=top_k,
        split_column=split_column,
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
        description="Run factor sector-neutral and beta-adjusted diagnostics",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Scored panel table (default: {DEFAULT_TABLE})",
    )
    parser.add_argument("--score-column", default=DEFAULT_SCORE_COLUMN)
    parser.add_argument("--target-column", default=DEFAULT_TARGET_COLUMN)
    parser.add_argument("--date-column", default="date")
    parser.add_argument("--sector-column", default=DEFAULT_SECTOR_COLUMN)
    parser.add_argument("--beta-column", default=None)
    parser.add_argument(
        "--split-column",
        default=DEFAULT_SPLIT_COLUMN,
        help="Optional split column for grouped diagnostics; use empty string to disable",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        report = validate_factor_neutrality(
            conn,
            table_name=args.table,
            score_column=args.score_column,
            target_column=args.target_column,
            date_column=args.date_column,
            sector_column=args.sector_column,
            beta_column=args.beta_column,
            top_k=args.top_k,
            split_column=args.split_column or None,
        )
    finally:
        conn.close()

    print("Factor neutrality diagnostics report")
    print(json.dumps(json_safe(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
