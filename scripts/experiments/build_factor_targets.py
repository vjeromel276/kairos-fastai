#!/usr/bin/env python3
"""Build baseline multi-factor panel targets from adjusted prices."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_SOURCE_TABLE = "sep_base"
DEFAULT_OUTPUT_TABLE = "factor_panel_targets_v1"
DEFAULT_PANEL_NAME = "large_cap_fixed"
DEFAULT_TARGET_HORIZONS = (21, 5)
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"invalid DuckDB identifier: {identifier}")
    return f'"{identifier}"'


def normalize_tickers(tickers: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        ticker_value = ticker.strip().upper()
        if not ticker_value or ticker_value in seen:
            continue
        normalized.append(ticker_value)
        seen.add(ticker_value)
    if not normalized:
        raise ValueError("at least one ticker is required")
    return normalized


def validate_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    if not horizons:
        raise ValueError("at least one target horizon is required")
    if any(horizon < 1 for horizon in horizons):
        raise ValueError("target horizons must be >= 1")
    normalized = tuple(dict.fromkeys(horizons))
    return normalized


def load_panel_prices(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    source_table: str = DEFAULT_SOURCE_TABLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    selected_tickers = normalize_tickers(tickers)
    source_identifier = quote_identifier(source_table)
    placeholders = ", ".join(["?"] * len(selected_tickers))
    filters = [
        f"ticker IN ({placeholders})",
        "date IS NOT NULL",
        "closeadj IS NOT NULL",
    ]
    params: list[object] = list(selected_tickers)
    if start_date:
        filters.append("date >= ?")
        params.append(start_date)
    if end_date:
        filters.append("date <= ?")
        params.append(end_date)

    query = f"""
        SELECT
            ticker,
            CAST(date AS DATE) AS date,
            CAST(closeadj AS DOUBLE) AS closeadj
        FROM {source_identifier}
        WHERE {' AND '.join(filters)}
        ORDER BY ticker, date
    """
    return conn.execute(query, params).fetchdf()


def add_horizon_targets(
    df: pd.DataFrame,
    horizon: int,
) -> pd.DataFrame:
    result = df.copy()
    future_close = result["closeadj"].shift(-horizon)
    prior_close = result["closeadj"].shift(horizon)
    target_column = f"future_{horizon}d_return"
    winner_column = f"winner_{horizon}d"
    prior_column = f"prior_{horizon}d_return"

    result[target_column] = future_close / result["closeadj"] - 1.0
    result[prior_column] = result["closeadj"] / prior_close - 1.0

    winner = pd.Series(pd.NA, index=result.index, dtype="Int64")
    target = result[target_column]
    winner.loc[target.notna()] = (target.loc[target.notna()] > 0).astype("int64")
    result[winner_column] = winner
    return result


def add_targets_for_ticker(
    prices: pd.DataFrame,
    horizons: tuple[int, ...],
    panel_name: str,
) -> pd.DataFrame:
    result = prices.sort_values("date").copy()
    result.insert(2, "panel_name", panel_name)
    for horizon in validate_horizons(horizons):
        result = add_horizon_targets(result, horizon=horizon)
    return result


def build_factor_targets(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    source_table: str = DEFAULT_SOURCE_TABLE,
    panel_name: str = DEFAULT_PANEL_NAME,
    horizons: tuple[int, ...] = DEFAULT_TARGET_HORIZONS,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    prices = load_panel_prices(
        conn,
        tickers=tickers,
        source_table=source_table,
        start_date=start_date,
        end_date=end_date,
    )
    if prices.empty:
        raise ValueError("no source rows found for selected target panel")

    parts = [
        add_targets_for_ticker(group, horizons=horizons, panel_name=panel_name)
        for _, group in prices.groupby("ticker", sort=False)
    ]
    return pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(
        drop=True
    )


def write_targets_table(
    conn: duckdb.DuckDBPyConnection,
    targets: pd.DataFrame,
    output_table: str = DEFAULT_OUTPUT_TABLE,
) -> int:
    output_identifier = quote_identifier(output_table)
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE {output_identifier} AS
        SELECT * FROM targets
        """
    )
    return conn.execute(f"SELECT COUNT(*) FROM {output_identifier}").fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build multi-factor panel targets from adjusted prices",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--tickers",
        nargs="+",
        required=True,
        help="Ticker list for the target panel, for example AAPL MSFT",
    )
    parser.add_argument(
        "--source-table",
        default=DEFAULT_SOURCE_TABLE,
        help=f"Source table containing ticker/date/closeadj (default: {DEFAULT_SOURCE_TABLE})",
    )
    parser.add_argument(
        "--output-table",
        default=DEFAULT_OUTPUT_TABLE,
        help=f"Output table to replace (default: {DEFAULT_OUTPUT_TABLE})",
    )
    parser.add_argument(
        "--panel-name",
        default=DEFAULT_PANEL_NAME,
        help=f"Panel name to record in output rows (default: {DEFAULT_PANEL_NAME})",
    )
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=list(DEFAULT_TARGET_HORIZONS),
        help="Forward target horizons in trading rows (default: 21 5)",
    )
    parser.add_argument("--start-date", default=None, help="Optional source start date")
    parser.add_argument("--end-date", default=None, help="Optional source end date")
    args = parser.parse_args()

    selected_tickers = normalize_tickers(args.tickers)
    horizons = validate_horizons(tuple(args.horizons))
    conn = duckdb.connect(args.db)
    try:
        targets = build_factor_targets(
            conn,
            tickers=selected_tickers,
            source_table=args.source_table,
            panel_name=args.panel_name,
            horizons=horizons,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        rows_written = write_targets_table(
            conn,
            targets,
            output_table=args.output_table,
        )
    finally:
        conn.close()

    logger.info(
        "Wrote %s target rows for %s to %s",
        f"{rows_written:,}",
        ", ".join(selected_tickers),
        args.output_table,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
