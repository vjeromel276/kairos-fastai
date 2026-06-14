#!/usr/bin/env python3
"""Build RSI experiment datasets from Sharadar SEP data."""

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

from scripts.experiments.rsi_features import (  # noqa: E402
    add_rsi_ema_features,
    add_rsi_slope_features,
    calculate_rsi,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_SOURCE_TABLE = "sep_base"
DEFAULT_OUTPUT_TABLE = "rsi_experiment_one_ticker_v1"
DEFAULT_PANEL_OUTPUT_TABLE = "rsi_experiment_panel_v1"
DEFAULT_RSI_WINDOW = 14
DEFAULT_HORIZON_DAYS = 5
FEATURE_SET_A = "A"
FEATURE_SET_B = "B"
FEATURE_SET_C = "C"
FEATURE_SET_ALL = "ALL"
FEATURE_SET_CHOICES = (FEATURE_SET_A, FEATURE_SET_B, FEATURE_SET_C, FEATURE_SET_ALL)
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"invalid DuckDB identifier: {identifier}")
    return f'"{identifier}"'


def load_one_ticker_prices(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    source_table: str = DEFAULT_SOURCE_TABLE,
) -> pd.DataFrame:
    """Load adjusted close prices for one ticker from the source table."""
    source_identifier = quote_identifier(source_table)
    query = f"""
        SELECT
            ticker,
            CAST(date AS DATE) AS date,
            CAST(closeadj AS DOUBLE) AS closeadj
        FROM {source_identifier}
        WHERE ticker = ?
          AND date IS NOT NULL
          AND closeadj IS NOT NULL
        ORDER BY date
    """
    return conn.execute(query, [ticker]).fetchdf()


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


def load_panel_prices(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    source_table: str = DEFAULT_SOURCE_TABLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Load adjusted close prices for a constrained ticker panel."""
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


def add_future_targets(
    df: pd.DataFrame,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> pd.DataFrame:
    """Add future return and direction targets without filling unavailable rows."""
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")

    result = df.copy()
    future_close = result["closeadj"].shift(-horizon_days)
    result[f"future_{horizon_days}d_return"] = future_close / result["closeadj"] - 1.0

    winner = pd.Series(pd.NA, index=result.index, dtype="Int64")
    target = result[f"future_{horizon_days}d_return"]
    winner.loc[target.notna()] = (target.loc[target.notna()] > 0).astype("int64")
    result[f"winner_{horizon_days}d"] = winner
    return result


def add_feature_columns(
    prices: pd.DataFrame,
    rsi_window: int = DEFAULT_RSI_WINDOW,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    feature_set: str = FEATURE_SET_A,
) -> pd.DataFrame:
    """Build RSI features and forward targets for one ticker price path."""
    result = prices.sort_values("date").copy()
    rsi_column = f"rsi_{rsi_window}"
    result[rsi_column] = calculate_rsi(result["closeadj"], window=rsi_window)

    normalized_feature_set = feature_set.upper()
    if normalized_feature_set in (FEATURE_SET_B, FEATURE_SET_ALL):
        result = add_rsi_slope_features(result, rsi_column=rsi_column)
    if normalized_feature_set in (FEATURE_SET_C, FEATURE_SET_ALL):
        result = add_rsi_ema_features(result, rsi_column=rsi_column)
    if normalized_feature_set not in FEATURE_SET_CHOICES:
        raise ValueError(f"feature_set must be one of: {', '.join(FEATURE_SET_CHOICES)}")

    return add_future_targets(result, horizon_days=horizon_days)


def build_one_ticker_dataset(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    source_table: str = DEFAULT_SOURCE_TABLE,
    rsi_window: int = DEFAULT_RSI_WINDOW,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    feature_set: str = FEATURE_SET_A,
) -> pd.DataFrame:
    """Build one-ticker RSI features and forward targets."""
    prices = load_one_ticker_prices(conn, ticker=ticker, source_table=source_table)
    if prices.empty:
        raise ValueError(f"no rows found for ticker {ticker} in {source_table}")

    return add_feature_columns(
        prices,
        rsi_window=rsi_window,
        horizon_days=horizon_days,
        feature_set=feature_set,
    )


def build_panel_dataset(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    source_table: str = DEFAULT_SOURCE_TABLE,
    rsi_window: int = DEFAULT_RSI_WINDOW,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    feature_set: str = FEATURE_SET_A,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Build RSI features and forward targets for a constrained ticker panel."""
    prices = load_panel_prices(
        conn,
        tickers=tickers,
        source_table=source_table,
        start_date=start_date,
        end_date=end_date,
    )
    if prices.empty:
        raise ValueError("no source rows found for selected panel")

    parts = [
        add_feature_columns(
            group,
            rsi_window=rsi_window,
            horizon_days=horizon_days,
            feature_set=feature_set,
        )
        for _, group in prices.groupby("ticker", sort=False)
    ]
    return pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(
        drop=True
    )


def write_dataset_table(
    conn: duckdb.DuckDBPyConnection,
    dataset: pd.DataFrame,
    output_table: str = DEFAULT_OUTPUT_TABLE,
) -> int:
    """Write the dataset to DuckDB, replacing the output table atomically."""
    output_identifier = quote_identifier(output_table)
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE {output_identifier} AS
        SELECT * FROM dataset
        """
    )
    return conn.execute(f"SELECT COUNT(*) FROM {output_identifier}").fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build RSI experiment datasets from sep_base",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    ticker_group = parser.add_mutually_exclusive_group(required=True)
    ticker_group.add_argument("--ticker", help="Single ticker to build, for example AAPL")
    ticker_group.add_argument(
        "--tickers",
        nargs="+",
        help="Small ticker list for panel mode, for example AAPL MSFT",
    )
    parser.add_argument(
        "--source-table",
        default=DEFAULT_SOURCE_TABLE,
        help=f"Source table containing ticker/date/closeadj columns (default: {DEFAULT_SOURCE_TABLE})",
    )
    parser.add_argument(
        "--output-table",
        default=None,
        help=(
            f"Output table to replace (single default: {DEFAULT_OUTPUT_TABLE}; "
            f"panel default: {DEFAULT_PANEL_OUTPUT_TABLE})"
        ),
    )
    parser.add_argument(
        "--rsi-window",
        type=int,
        default=DEFAULT_RSI_WINDOW,
        help=f"RSI lookback window (default: {DEFAULT_RSI_WINDOW})",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=DEFAULT_HORIZON_DAYS,
        help=f"Future return horizon in trading rows (default: {DEFAULT_HORIZON_DAYS})",
    )
    parser.add_argument(
        "--feature-set",
        choices=FEATURE_SET_CHOICES,
        default=FEATURE_SET_A,
        help=(
            "Feature set to build: A = RSI today, B = RSI slopes, "
            "C = RSI EMA recency, ALL = all RSI feature columns"
        ),
    )
    parser.add_argument("--start-date", default=None, help="Optional source start date")
    parser.add_argument("--end-date", default=None, help="Optional source end date")
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        if args.ticker:
            selected_tickers = [args.ticker.upper()]
            output_table = args.output_table or DEFAULT_OUTPUT_TABLE
            dataset = build_one_ticker_dataset(
                conn,
                ticker=args.ticker.upper(),
                source_table=args.source_table,
                rsi_window=args.rsi_window,
                horizon_days=args.horizon_days,
                feature_set=args.feature_set,
            )
        else:
            selected_tickers = normalize_tickers(args.tickers)
            output_table = args.output_table or DEFAULT_PANEL_OUTPUT_TABLE
            dataset = build_panel_dataset(
                conn,
                tickers=selected_tickers,
                source_table=args.source_table,
                rsi_window=args.rsi_window,
                horizon_days=args.horizon_days,
                feature_set=args.feature_set,
                start_date=args.start_date,
                end_date=args.end_date,
            )
        rows_written = write_dataset_table(conn, dataset, output_table=output_table)
    finally:
        conn.close()

    logger.info(
        "Wrote %s rows for %s to %s",
        f"{rows_written:,}",
        ", ".join(selected_tickers),
        output_table,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
