#!/usr/bin/env python3
"""Build a one-ticker RSI experiment dataset from Sharadar SEP data."""

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

from scripts.experiments.rsi_features import calculate_rsi  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_SOURCE_TABLE = "sep_base"
DEFAULT_OUTPUT_TABLE = "rsi_experiment_one_ticker_v1"
DEFAULT_RSI_WINDOW = 14
DEFAULT_HORIZON_DAYS = 5
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


def build_one_ticker_dataset(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    source_table: str = DEFAULT_SOURCE_TABLE,
    rsi_window: int = DEFAULT_RSI_WINDOW,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> pd.DataFrame:
    """Build feature set A and 5-day targets for one ticker."""
    prices = load_one_ticker_prices(conn, ticker=ticker, source_table=source_table)
    if prices.empty:
        raise ValueError(f"no rows found for ticker {ticker} in {source_table}")

    result = prices.copy()
    result[f"rsi_{rsi_window}"] = calculate_rsi(result["closeadj"], window=rsi_window)
    return add_future_targets(result, horizon_days=horizon_days)


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
        description="Build a one-ticker RSI experiment dataset from sep_base",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument("--ticker", required=True, help="Ticker to build, for example AAPL")
    parser.add_argument(
        "--source-table",
        default=DEFAULT_SOURCE_TABLE,
        help=f"Source table containing ticker/date/closeadj columns (default: {DEFAULT_SOURCE_TABLE})",
    )
    parser.add_argument(
        "--output-table",
        default=DEFAULT_OUTPUT_TABLE,
        help=f"Output table to replace (default: {DEFAULT_OUTPUT_TABLE})",
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
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        dataset = build_one_ticker_dataset(
            conn,
            ticker=args.ticker,
            source_table=args.source_table,
            rsi_window=args.rsi_window,
            horizon_days=args.horizon_days,
        )
        rows_written = write_dataset_table(conn, dataset, output_table=args.output_table)
    finally:
        conn.close()

    logger.info(
        "Wrote %s rows for %s to %s",
        f"{rows_written:,}",
        args.ticker,
        args.output_table,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
