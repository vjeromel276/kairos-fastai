#!/usr/bin/env python3
"""Build the universe price/regime factor panel with DuckDB window functions."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.build_factor_targets import quote_identifier  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DB = "data/kairos-fastai.duckdb"
DEFAULT_SOURCE_TABLE = "sep_base"
DEFAULT_SPY_TABLE = "sfp"
DEFAULT_TICKERS_TABLE = "tickers"
DEFAULT_UNIVERSE_TABLE = "universe_fastai_v1"
DEFAULT_OUTPUT_TABLE = "factor_panel_universe_price_regime_v1"
DEFAULT_SOURCE_START_DATE = "2016-12-15"
DEFAULT_START_DATE = "2018-01-02"


def date_literal(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"DATE '{parsed.isoformat()}'"


def optional_end_filter(alias: str, end_date: str | None) -> str:
    if not end_date:
        return ""
    return f" AND {alias}.date <= {date_literal(end_date)}"


def build_universe_price_regime_panel(
    conn: duckdb.DuckDBPyConnection,
    output_table: str = DEFAULT_OUTPUT_TABLE,
    source_table: str = DEFAULT_SOURCE_TABLE,
    spy_table: str = DEFAULT_SPY_TABLE,
    tickers_table: str = DEFAULT_TICKERS_TABLE,
    universe_table: str = DEFAULT_UNIVERSE_TABLE,
    source_start_date: str = DEFAULT_SOURCE_START_DATE,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
) -> int:
    output_identifier = quote_identifier(output_table)
    source_identifier = quote_identifier(source_table)
    spy_identifier = quote_identifier(spy_table)
    tickers_identifier = quote_identifier(tickers_table)
    universe_identifier = quote_identifier(universe_table)
    source_start = date_literal(source_start_date)
    output_start = date_literal(start_date)

    universe_end_filter = optional_end_filter("u", end_date)
    source_end_filter = optional_end_filter("s", end_date)
    spy_end_filter = optional_end_filter("s", end_date)
    output_end_filter = optional_end_filter("pf", end_date)

    query = f"""
        CREATE OR REPLACE TABLE {output_identifier} AS
        WITH selected_tickers AS (
            SELECT DISTINCT ticker
            FROM {universe_identifier} AS u
            WHERE u.ticker IS NOT NULL
              AND u.date >= {output_start}
              {universe_end_filter}
        ),
        universe_membership AS (
            SELECT DISTINCT ticker, CAST(date AS DATE) AS date
            FROM {universe_identifier} AS u
            WHERE u.ticker IS NOT NULL
              AND u.date >= {output_start}
              {universe_end_filter}
        ),
        ticker_metadata AS (
            SELECT ticker, exchange, sector, industry
            FROM (
                SELECT
                    t.ticker,
                    t.exchange,
                    t.sector,
                    t.industry,
                    ROW_NUMBER() OVER (
                        PARTITION BY t.ticker
                        ORDER BY t.lastupdated DESC NULLS LAST
                    ) AS metadata_rank
                FROM {tickers_identifier} AS t
                INNER JOIN selected_tickers AS st
                    ON st.ticker = t.ticker
            )
            WHERE metadata_rank = 1
        ),
        spy_source AS (
            SELECT
                CAST(s.date AS DATE) AS date,
                CAST(s.closeadj AS DOUBLE) AS closeadj
            FROM {spy_identifier} AS s
            WHERE s.ticker = 'SPY'
              AND s.date IS NOT NULL
              AND s.closeadj IS NOT NULL
              AND s.date >= {source_start}
              {spy_end_filter}
        ),
        spy_base AS (
            SELECT
                date,
                closeadj,
                closeadj / LAG(closeadj, 1) OVER spy_order - 1.0 AS spy_return_1d,
                closeadj / LAG(closeadj, 21) OVER spy_order - 1.0 AS regime_spy_return_21d
            FROM spy_source
            WINDOW spy_order AS (ORDER BY date)
        ),
        spy_regime_base AS (
            SELECT
                date,
                spy_return_1d,
                regime_spy_return_21d,
                CASE
                    WHEN COUNT(closeadj) OVER spy_50 = 50
                    THEN closeadj / AVG(closeadj) OVER spy_50 - 1.0
                END AS regime_spy_trend_50d,
                CASE
                    WHEN COUNT(closeadj) OVER spy_200 = 200
                    THEN closeadj / AVG(closeadj) OVER spy_200 - 1.0
                END AS regime_spy_trend_200d,
                CASE
                    WHEN COUNT(spy_return_1d) OVER spy_21 = 21
                    THEN STDDEV_POP(spy_return_1d) OVER spy_21 * SQRT(252.0)
                END AS regime_spy_realized_vol_21d,
                CASE
                    WHEN COUNT(spy_return_1d) OVER spy_63 = 63
                    THEN STDDEV_POP(spy_return_1d) OVER spy_63 * SQRT(252.0)
                END AS regime_spy_realized_vol_63d,
                CASE
                    WHEN COUNT(closeadj) OVER spy_252 = 252
                    THEN closeadj / MAX(closeadj) OVER spy_252 - 1.0
                END AS regime_spy_drawdown_252d
            FROM spy_base
            WINDOW
                spy_21 AS (ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW),
                spy_50 AS (ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
                spy_63 AS (ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW),
                spy_200 AS (ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
                spy_252 AS (ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
        ),
        spy_regime AS (
            SELECT
                date,
                spy_return_1d,
                regime_spy_return_21d,
                regime_spy_trend_50d,
                CASE
                    WHEN regime_spy_trend_50d IS NULL THEN NULL
                    WHEN regime_spy_trend_50d > 0 THEN 1.0
                    ELSE 0.0
                END AS regime_spy_above_ma_50d,
                regime_spy_trend_200d,
                CASE
                    WHEN regime_spy_trend_200d IS NULL THEN NULL
                    WHEN regime_spy_trend_200d > 0 THEN 1.0
                    ELSE 0.0
                END AS regime_spy_above_ma_200d,
                regime_spy_realized_vol_21d,
                regime_spy_realized_vol_63d,
                regime_spy_drawdown_252d,
                regime_spy_return_21d
                    / NULLIF(regime_spy_realized_vol_21d, 0.0)
                    AS regime_spy_risk_on_score_21d
            FROM spy_regime_base
        ),
        price_source AS (
            SELECT
                s.ticker,
                CAST(s.date AS DATE) AS date,
                CAST(s.closeadj AS DOUBLE) AS closeadj,
                CAST(s.volume AS DOUBLE) AS volume
            FROM {source_identifier} AS s
            INNER JOIN selected_tickers AS st
                ON st.ticker = s.ticker
            WHERE s.date IS NOT NULL
              AND s.closeadj IS NOT NULL
              AND s.date >= {source_start}
              {source_end_filter}
        ),
        price_base AS (
            SELECT
                p.ticker,
                p.date,
                'universe_fastai_v1' AS panel_name,
                p.closeadj,
                p.volume,
                LEAD(p.closeadj, 21) OVER ticker_order / p.closeadj - 1.0
                    AS future_21d_return,
                p.closeadj / LAG(p.closeadj, 21) OVER ticker_order - 1.0
                    AS prior_21d_return,
                LEAD(p.closeadj, 5) OVER ticker_order / p.closeadj - 1.0
                    AS future_5d_return,
                p.closeadj / LAG(p.closeadj, 5) OVER ticker_order - 1.0
                    AS prior_5d_return,
                p.closeadj / LAG(p.closeadj, 1) OVER ticker_order - 1.0
                    AS px_return_1d,
                p.closeadj / LAG(p.closeadj, 5) OVER ticker_order - 1.0
                    AS px_return_5d,
                p.closeadj / LAG(p.closeadj, 21) OVER ticker_order - 1.0
                    AS px_return_21d,
                p.closeadj / LAG(p.closeadj, 63) OVER ticker_order - 1.0
                    AS px_return_63d,
                p.closeadj / LAG(p.closeadj, 126) OVER ticker_order - 1.0
                    AS px_return_126d,
                p.closeadj / LAG(p.closeadj, 252) OVER ticker_order - 1.0
                    AS px_return_252d,
                p.closeadj * p.volume AS liq_dollar_volume
            FROM price_source AS p
            WINDOW ticker_order AS (PARTITION BY p.ticker ORDER BY p.date)
        ),
        price_features AS (
            SELECT
                pb.*,
                CASE
                    WHEN future_21d_return IS NULL THEN NULL
                    WHEN future_21d_return > 0 THEN 1
                    ELSE 0
                END AS winner_21d,
                CASE
                    WHEN future_5d_return IS NULL THEN NULL
                    WHEN future_5d_return > 0 THEN 1
                    ELSE 0
                END AS winner_5d,
                CASE
                    WHEN COUNT(closeadj) OVER ticker_21 = 21
                    THEN closeadj / AVG(closeadj) OVER ticker_21 - 1.0
                END AS px_ma_dist_21d,
                CASE
                    WHEN COUNT(closeadj) OVER ticker_63 = 63
                    THEN closeadj / AVG(closeadj) OVER ticker_63 - 1.0
                END AS px_ma_dist_63d,
                CASE
                    WHEN COUNT(closeadj) OVER ticker_252 = 252
                    THEN closeadj / AVG(closeadj) OVER ticker_252 - 1.0
                END AS px_ma_dist_252d,
                CASE
                    WHEN COUNT(closeadj) OVER ticker_252 = 252
                    THEN closeadj / MAX(closeadj) OVER ticker_252 - 1.0
                END AS px_drawdown_252d,
                -px_return_5d AS px_short_reversal_5d,
                closeadj >= 5.0 AS liq_is_price_eligible,
                CASE
                    WHEN COUNT(volume) OVER ticker_20 = 20
                    THEN AVG(volume) OVER ticker_20
                END AS liq_volume_avg_20d,
                CASE
                    WHEN COUNT(liq_dollar_volume) OVER ticker_20 = 20
                    THEN AVG(liq_dollar_volume) OVER ticker_20
                END AS liq_adv_20d,
                CASE
                    WHEN COUNT(volume) OVER ticker_20 = 20
                    THEN volume / NULLIF(AVG(volume) OVER ticker_20, 0.0)
                END AS liq_rel_volume_20d,
                CASE
                    WHEN COUNT(volume) OVER ticker_60 = 60
                    THEN AVG(volume) OVER ticker_60
                END AS liq_volume_avg_60d,
                CASE
                    WHEN COUNT(liq_dollar_volume) OVER ticker_60 = 60
                    THEN AVG(liq_dollar_volume) OVER ticker_60
                END AS liq_adv_60d,
                CASE
                    WHEN COUNT(volume) OVER ticker_60 = 60
                    THEN volume / NULLIF(AVG(volume) OVER ticker_60, 0.0)
                END AS liq_rel_volume_60d,
                CASE
                    WHEN COUNT(px_return_1d) OVER ticker_21 = 21
                     AND COUNT(sr.spy_return_1d) OVER ticker_21 = 21
                     AND VAR_POP(sr.spy_return_1d) OVER ticker_21 > 0
                    THEN COVAR_POP(px_return_1d, sr.spy_return_1d) OVER ticker_21
                         / VAR_POP(sr.spy_return_1d) OVER ticker_21
                END AS risk_beta_spy_21d
            FROM price_base AS pb
            LEFT JOIN spy_regime AS sr
                ON sr.date = pb.date
            WINDOW
                ticker_20 AS (
                    PARTITION BY pb.ticker
                    ORDER BY pb.date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ),
                ticker_21 AS (
                    PARTITION BY pb.ticker
                    ORDER BY pb.date
                    ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
                ),
                ticker_60 AS (
                    PARTITION BY pb.ticker
                    ORDER BY pb.date
                    ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                ),
                ticker_63 AS (
                    PARTITION BY pb.ticker
                    ORDER BY pb.date
                    ROWS BETWEEN 62 PRECEDING AND CURRENT ROW
                ),
                ticker_252 AS (
                    PARTITION BY pb.ticker
                    ORDER BY pb.date
                    ROWS BETWEEN 251 PRECEDING AND CURRENT ROW
                )
        ),
        output_rows AS (
            SELECT pf.*
            FROM price_features AS pf
            INNER JOIN universe_membership AS u
                ON u.ticker = pf.ticker
               AND u.date = pf.date
            WHERE pf.date >= {output_start}
              {output_end_filter}
        ),
        breadth AS (
            SELECT
                date,
                AVG(
                    CASE
                        WHEN px_return_21d IS NULL THEN NULL
                        WHEN px_return_21d > 0 THEN 1.0
                        ELSE 0.0
                    END
                ) AS regime_breadth_px_return_21d_positive
            FROM output_rows
            GROUP BY date
        )
        SELECT
            o.ticker,
            o.date,
            o.panel_name,
            o.closeadj,
            o.volume,
            o.future_21d_return,
            o.prior_21d_return,
            o.winner_21d,
            o.future_5d_return,
            o.prior_5d_return,
            o.winner_5d,
            tm.exchange,
            tm.sector,
            tm.industry,
            o.px_return_1d,
            o.px_return_5d,
            o.px_return_21d,
            o.px_return_63d,
            o.px_return_126d,
            o.px_return_252d,
            o.px_ma_dist_21d,
            o.px_ma_dist_63d,
            o.px_ma_dist_252d,
            o.px_drawdown_252d,
            o.px_short_reversal_5d,
            o.liq_dollar_volume,
            o.liq_is_price_eligible,
            o.liq_volume_avg_20d,
            o.liq_adv_20d,
            o.liq_rel_volume_20d,
            o.liq_volume_avg_60d,
            o.liq_adv_60d,
            o.liq_rel_volume_60d,
            COALESCE(o.liq_adv_20d >= 1000000.0, FALSE) AS liq_is_adv20_eligible,
            CAST(NULL AS DOUBLE) AS liq_turnover,
            o.liq_is_price_eligible
                AND COALESCE(o.liq_adv_20d >= 1000000.0, FALSE)
                AS liq_is_liquid,
            o.risk_beta_spy_21d,
            sr.regime_spy_return_21d,
            sr.regime_spy_trend_50d,
            sr.regime_spy_above_ma_50d,
            sr.regime_spy_trend_200d,
            sr.regime_spy_above_ma_200d,
            sr.regime_spy_realized_vol_21d,
            sr.regime_spy_realized_vol_63d,
            sr.regime_spy_drawdown_252d,
            sr.regime_spy_risk_on_score_21d,
            b.regime_breadth_px_return_21d_positive
        FROM output_rows AS o
        LEFT JOIN ticker_metadata AS tm
            ON tm.ticker = o.ticker
        LEFT JOIN spy_regime AS sr
            ON sr.date = o.date
        LEFT JOIN breadth AS b
            ON b.date = o.date
        ORDER BY o.date, o.ticker
    """
    conn.execute(query)
    return conn.execute(f"SELECT COUNT(*) FROM {output_identifier}").fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the universe price/regime factor panel in DuckDB",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB path (default: {DEFAULT_DB})")
    parser.add_argument(
        "--source-table",
        default=DEFAULT_SOURCE_TABLE,
        help=f"Price source table (default: {DEFAULT_SOURCE_TABLE})",
    )
    parser.add_argument(
        "--spy-table",
        default=DEFAULT_SPY_TABLE,
        help=f"SPY source table (default: {DEFAULT_SPY_TABLE})",
    )
    parser.add_argument(
        "--tickers-table",
        default=DEFAULT_TICKERS_TABLE,
        help=f"Ticker metadata table (default: {DEFAULT_TICKERS_TABLE})",
    )
    parser.add_argument(
        "--universe-table",
        default=DEFAULT_UNIVERSE_TABLE,
        help=f"Universe membership table (default: {DEFAULT_UNIVERSE_TABLE})",
    )
    parser.add_argument(
        "--output-table",
        default=DEFAULT_OUTPUT_TABLE,
        help=f"Output table to replace (default: {DEFAULT_OUTPUT_TABLE})",
    )
    parser.add_argument(
        "--source-start-date",
        default=DEFAULT_SOURCE_START_DATE,
        help=f"Warmup source start date (default: {DEFAULT_SOURCE_START_DATE})",
    )
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help=f"Output membership start date (default: {DEFAULT_START_DATE})",
    )
    parser.add_argument("--end-date", default=None, help="Optional source/output end date")
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    try:
        rows_written = build_universe_price_regime_panel(
            conn,
            output_table=args.output_table,
            source_table=args.source_table,
            spy_table=args.spy_table,
            tickers_table=args.tickers_table,
            universe_table=args.universe_table,
            source_start_date=args.source_start_date,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    finally:
        conn.close()

    logger.info(
        "Wrote %s universe price/regime factor rows to %s",
        f"{rows_written:,}",
        args.output_table,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
