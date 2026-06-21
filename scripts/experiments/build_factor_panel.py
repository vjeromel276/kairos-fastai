#!/usr/bin/env python3
"""Build bucketed multi-factor experiment panels in DuckDB."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.build_factor_targets import (  # noqa: E402
    add_targets_for_ticker,
    normalize_tickers,
    quote_identifier,
    validate_horizons,
)
from scripts.experiments.cross_sectional_features import (  # noqa: E402
    add_cross_sectional_rank_features,
    add_cross_sectional_zscore_features,
    add_market_relative_features,
)
from scripts.experiments.fundamental_quality_features import (  # noqa: E402
    add_fundamental_quality_features,
)
from scripts.experiments.price_behavior_features import (  # noqa: E402
    add_price_behavior_features,
    add_price_behavior_features_for_panel,
)
from scripts.experiments.regime_features import add_regime_context_features  # noqa: E402
from scripts.experiments.valuation_features import add_valuation_features  # noqa: E402
from scripts.experiments.volatility_risk_features import (  # noqa: E402
    add_volatility_risk_features_for_panel,
)
from scripts.experiments.volume_liquidity_features import (  # noqa: E402
    add_volume_liquidity_features_for_panel,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_SOURCE_TABLE = "sep_base"
DEFAULT_SPY_TABLE = "sfp"
DEFAULT_DAILY_TABLE = "daily"
DEFAULT_SF1_TABLE = "sf1"
DEFAULT_TICKERS_TABLE = "tickers"
DEFAULT_UNIVERSE_TABLE = "universe_fastai_v1"
DEFAULT_OUTPUT_TABLE = "factor_panel_v1"
DEFAULT_PANEL = "large_cap_fixed"
DEFAULT_BUCKETS = ("price",)
SUPPORTED_BUCKETS = (
    "price",
    "volume",
    "volatility",
    "fundamental",
    "valuation",
    "regime",
    "cross_sectional",
)
FIXED_LARGE_CAP_TICKERS = (
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "JPM",
    "XOM",
    "UNH",
    "WMT",
    "PG",
    "JNJ",
    "HD",
    "MA",
    "BAC",
    "KO",
    "PFE",
    "CSCO",
    "CVX",
    "ORCL",
)


def parse_buckets(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return DEFAULT_BUCKETS
    buckets: list[str] = []
    for value in values:
        buckets.extend(part.strip().lower() for part in value.split(","))
    normalized = tuple(dict.fromkeys(bucket for bucket in buckets if bucket))
    unknown = sorted(set(normalized) - set(SUPPORTED_BUCKETS))
    if unknown:
        raise ValueError(f"unsupported buckets: {', '.join(unknown)}")
    return normalized


def table_exists(conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    try:
        conn.execute(f"SELECT 1 FROM {quote_identifier(table_name)} LIMIT 1")
    except duckdb.CatalogException:
        return False
    return True


def table_columns(conn: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    if not table_exists(conn, table_name):
        return []
    return [
        row[1]
        for row in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()
    ]


def load_universe_tickers(
    conn: duckdb.DuckDBPyConnection,
    universe_table: str = DEFAULT_UNIVERSE_TABLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[str]:
    columns = table_columns(conn, universe_table)
    if not columns:
        raise ValueError(f"universe table not found: {universe_table}")
    if "ticker" not in columns:
        raise ValueError(f"universe table lacks ticker column: {universe_table}")

    filters = ["ticker IS NOT NULL"]
    params: list[object] = []
    if "date" in columns and start_date:
        filters.append("date >= ?")
        params.append(start_date)
    if "date" in columns and end_date:
        filters.append("date <= ?")
        params.append(end_date)

    query = f"""
        SELECT DISTINCT ticker
        FROM {quote_identifier(universe_table)}
        WHERE {' AND '.join(filters)}
        ORDER BY ticker
    """
    tickers = [row[0] for row in conn.execute(query, params).fetchall()]
    return normalize_tickers(tickers)


def resolve_panel_tickers(
    conn: duckdb.DuckDBPyConnection,
    panel: str,
    tickers: list[str] | None = None,
    universe_table: str = DEFAULT_UNIVERSE_TABLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[str]:
    explicit_tickers = normalize_tickers(tickers) if tickers else None
    if panel == "large_cap_fixed":
        return explicit_tickers or list(FIXED_LARGE_CAP_TICKERS)
    if panel == "universe_fastai_v1":
        universe_tickers = load_universe_tickers(
            conn,
            universe_table=universe_table,
            start_date=start_date,
            end_date=end_date,
        )
        if explicit_tickers is None:
            return universe_tickers
        universe_set = set(universe_tickers)
        selected = [ticker for ticker in explicit_tickers if ticker in universe_set]
        if not selected:
            raise ValueError("no requested tickers are present in universe_fastai_v1")
        return selected
    raise ValueError("panel must be large_cap_fixed or universe_fastai_v1")


def load_price_panel(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    source_table: str = DEFAULT_SOURCE_TABLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    selected_tickers = normalize_tickers(tickers)
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
            CAST(closeadj AS DOUBLE) AS closeadj,
            CAST(volume AS DOUBLE) AS volume
        FROM {quote_identifier(source_table)}
        WHERE {' AND '.join(filters)}
        ORDER BY ticker, date
    """
    return conn.execute(query, params).fetchdf()


def load_spy_prices(
    conn: duckdb.DuckDBPyConnection,
    spy_table: str = DEFAULT_SPY_TABLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    if not table_exists(conn, spy_table):
        return pd.DataFrame(columns=["date", "closeadj"])
    filters = ["ticker = 'SPY'", "date IS NOT NULL", "closeadj IS NOT NULL"]
    params: list[object] = []
    if start_date:
        filters.append("date >= ?")
        params.append(start_date)
    if end_date:
        filters.append("date <= ?")
        params.append(end_date)
    query = f"""
        SELECT CAST(date AS DATE) AS date, CAST(closeadj AS DOUBLE) AS closeadj
        FROM {quote_identifier(spy_table)}
        WHERE {' AND '.join(filters)}
        ORDER BY date
    """
    return conn.execute(query, params).fetchdf()


def load_ticker_metadata(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    tickers_table: str = DEFAULT_TICKERS_TABLE,
) -> pd.DataFrame:
    columns = table_columns(conn, tickers_table)
    if not columns:
        return pd.DataFrame(columns=["ticker"])

    metadata_columns = [
        column for column in ("exchange", "sector", "industry") if column in columns
    ]
    if not metadata_columns:
        return pd.DataFrame(columns=["ticker"])

    selected_tickers = normalize_tickers(tickers)
    if not selected_tickers:
        return pd.DataFrame(columns=["ticker", *metadata_columns])

    placeholders = ", ".join(["?"] * len(selected_tickers))
    select_columns = ["ticker", *metadata_columns]
    internal_columns = list(select_columns)
    if "lastupdated" in columns:
        internal_columns.append("lastupdated")
    select_list = ", ".join(quote_identifier(column) for column in internal_columns)
    query = f"""
        SELECT {select_list}
        FROM {quote_identifier(tickers_table)}
        WHERE ticker IN ({placeholders})
        ORDER BY ticker
    """
    metadata = conn.execute(query, selected_tickers).fetchdf()
    if metadata.empty:
        return pd.DataFrame(columns=["ticker", *metadata_columns])

    if "lastupdated" in metadata.columns:
        metadata["_metadata_lastupdated"] = pd.to_datetime(
            metadata["lastupdated"],
            errors="coerce",
        )
        metadata = (
            metadata.sort_values(
                ["ticker", "_metadata_lastupdated"],
                na_position="first",
            )
            .drop_duplicates("ticker", keep="last")
            .drop(columns=["lastupdated", "_metadata_lastupdated"])
        )
    else:
        metadata = metadata.drop_duplicates("ticker", keep="last")
    return metadata[select_columns].reset_index(drop=True)


def add_ticker_metadata(panel: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    if metadata.empty or "ticker" not in metadata.columns:
        return panel
    metadata_columns = [
        column for column in ("exchange", "sector", "industry") if column in metadata.columns
    ]
    if not metadata_columns:
        return panel
    clean_metadata = metadata[["ticker", *metadata_columns]].drop_duplicates("ticker")
    return panel.merge(clean_metadata, on="ticker", how="left")


def load_universe_membership(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    universe_table: str = DEFAULT_UNIVERSE_TABLE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    columns = table_columns(conn, universe_table)
    if not columns:
        raise ValueError(f"universe table not found: {universe_table}")
    required = {"ticker", "date"}
    missing = sorted(required - set(columns))
    if missing:
        raise ValueError(
            f"universe table lacks required columns: {', '.join(missing)}"
        )

    selected_tickers = normalize_tickers(tickers)
    if not selected_tickers:
        return pd.DataFrame(columns=["ticker", "date"])

    placeholders = ", ".join(["?"] * len(selected_tickers))
    filters = [f"ticker IN ({placeholders})", "date IS NOT NULL"]
    params: list[object] = list(selected_tickers)
    if start_date:
        filters.append("date >= ?")
        params.append(start_date)
    if end_date:
        filters.append("date <= ?")
        params.append(end_date)

    query = f"""
        SELECT DISTINCT ticker, CAST(date AS DATE) AS date
        FROM {quote_identifier(universe_table)}
        WHERE {' AND '.join(filters)}
    """
    return conn.execute(query, params).fetchdf()


def filter_to_universe_membership(
    panel: pd.DataFrame,
    membership: pd.DataFrame,
) -> pd.DataFrame:
    if membership.empty:
        return panel.iloc[0:0].copy()

    result = panel.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    clean_membership = membership[["ticker", "date"]].drop_duplicates().copy()
    clean_membership["date"] = pd.to_datetime(
        clean_membership["date"],
        errors="coerce",
    )
    return result.merge(clean_membership, on=["ticker", "date"], how="inner")


def load_optional_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    tickers: list[str],
    candidate_columns: tuple[str, ...],
    end_date: str | None = None,
    date_filter_column: str = "date",
) -> pd.DataFrame:
    columns = table_columns(conn, table_name)
    if not columns:
        return pd.DataFrame(columns=["ticker", date_filter_column])
    selected_columns = [column for column in candidate_columns if column in columns]
    if "ticker" not in selected_columns:
        selected_columns.insert(0, "ticker")
    if date_filter_column in columns and date_filter_column not in selected_columns:
        selected_columns.insert(1, date_filter_column)

    selected_tickers = normalize_tickers(tickers)
    placeholders = ", ".join(["?"] * len(selected_tickers))
    filters = [f"ticker IN ({placeholders})"]
    params: list[object] = list(selected_tickers)
    if end_date and date_filter_column in columns:
        filters.append(f"{date_filter_column} <= ?")
        params.append(end_date)

    select_list = ", ".join(quote_identifier(column) for column in selected_columns)
    query = f"""
        SELECT {select_list}
        FROM {quote_identifier(table_name)}
        WHERE {' AND '.join(filters)}
    """
    return conn.execute(query, params).fetchdf()


def filter_output_dates(
    panel: pd.DataFrame,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    result = panel.copy()
    dates = pd.to_datetime(result["date"], errors="coerce")
    if start_date:
        result = result[dates >= pd.Timestamp(start_date)]
        dates = pd.to_datetime(result["date"], errors="coerce")
    if end_date:
        result = result[dates <= pd.Timestamp(end_date)]
    return result.copy()


def build_target_base(
    prices: pd.DataFrame,
    panel_name: str,
    horizons: tuple[int, ...],
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    if prices.empty:
        raise ValueError("no source rows found for selected factor panel")
    parts = [
        add_targets_for_ticker(group, horizons=horizons, panel_name=panel_name)
        for _, group in prices.groupby("ticker", sort=False)
    ]
    panel = pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"])
    return filter_output_dates(panel, start_date=start_date, end_date=end_date)


def add_cross_sectional_bucket(panel: pd.DataFrame, spy_prices: pd.DataFrame) -> pd.DataFrame:
    rank_columns = [
        column
        for column in ("px_return_21d", "liq_dollar_volume", "risk_realized_vol_21d")
        if column in panel.columns
    ]
    if not rank_columns:
        raise ValueError("cross_sectional bucket requires prior price/liquidity/risk features")

    result = add_cross_sectional_rank_features(panel, rank_columns)
    zscore_columns = [
        column
        for column in ("liq_dollar_volume", "risk_realized_vol_21d")
        if column in result.columns
    ]
    if zscore_columns:
        result = add_cross_sectional_zscore_features(result, zscore_columns)
    if "px_return_21d" in result.columns and not spy_prices.empty:
        spy_features = add_price_behavior_features(
            spy_prices,
            return_periods=(21,),
            ma_windows=(),
            drawdown_windows=(),
            short_reversal_period=21,
        )
        result = add_market_relative_features(result, spy_features, ["px_return_21d"])
    return result


def apply_feature_buckets(
    conn: duckdb.DuckDBPyConnection,
    panel: pd.DataFrame,
    tickers: list[str],
    buckets: tuple[str, ...],
    end_date: str | None = None,
    spy_table: str = DEFAULT_SPY_TABLE,
    daily_table: str = DEFAULT_DAILY_TABLE,
    sf1_table: str = DEFAULT_SF1_TABLE,
    source_start_date: str | None = None,
) -> pd.DataFrame:
    result = panel.copy()
    spy_prices: pd.DataFrame | None = None

    for bucket in buckets:
        if bucket == "price":
            result = add_price_behavior_features_for_panel(result)
        elif bucket == "volume":
            result = add_volume_liquidity_features_for_panel(result)
        elif bucket == "volatility":
            spy_prices = spy_prices if spy_prices is not None else load_spy_prices(
                conn,
                spy_table=spy_table,
                start_date=source_start_date,
                end_date=end_date,
            )
            result = add_volatility_risk_features_for_panel(
                result,
                market_proxy=spy_prices,
            )
        elif bucket == "fundamental":
            fundamentals = load_optional_table(
                conn,
                sf1_table,
                tickers,
                candidate_columns=(
                    "ticker",
                    "dimension",
                    "datekey",
                    "reportperiod",
                    "calendardate",
                    "lastupdated",
                    "grossmargin",
                    "opmargin",
                    "netmargin",
                    "roa",
                    "roe",
                    "roic",
                    "revenue",
                    "revenueusd",
                    "gp",
                    "ebit",
                    "netinc",
                    "assets",
                    "equity",
                    "debt",
                    "liabilities",
                ),
                end_date=end_date,
                date_filter_column="datekey",
            )
            result = add_fundamental_quality_features(result, fundamentals)
        elif bucket == "valuation":
            daily = load_optional_table(
                conn,
                daily_table,
                tickers,
                candidate_columns=("ticker", "date", "pe", "ps", "pb", "evebit", "evebitda", "marketcap"),
                end_date=end_date,
                date_filter_column="date",
            )
            fundamentals = load_optional_table(
                conn,
                sf1_table,
                tickers,
                candidate_columns=(
                    "ticker",
                    "dimension",
                    "datekey",
                    "reportperiod",
                    "calendardate",
                    "lastupdated",
                    "fcf",
                ),
                end_date=end_date,
                date_filter_column="datekey",
            )
            if fundamentals.empty:
                fundamentals = None
            result = add_valuation_features(result, daily, fundamentals=fundamentals)
        elif bucket == "regime":
            spy_prices = spy_prices if spy_prices is not None else load_spy_prices(
                conn,
                spy_table=spy_table,
                start_date=source_start_date,
                end_date=end_date,
            )
            breadth_columns = ("px_return_21d",) if "px_return_21d" in result.columns else ()
            result = add_regime_context_features(
                result,
                spy_prices,
                breadth_columns=breadth_columns,
            )
        elif bucket == "cross_sectional":
            spy_prices = spy_prices if spy_prices is not None else load_spy_prices(
                conn,
                spy_table=spy_table,
                start_date=source_start_date,
                end_date=end_date,
            )
            result = add_cross_sectional_bucket(result, spy_prices)
    return result.sort_values(["ticker", "date"]).reset_index(drop=True)


def build_factor_panel(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    panel_name: str = DEFAULT_PANEL,
    buckets: tuple[str, ...] = DEFAULT_BUCKETS,
    source_table: str = DEFAULT_SOURCE_TABLE,
    spy_table: str = DEFAULT_SPY_TABLE,
    daily_table: str = DEFAULT_DAILY_TABLE,
    sf1_table: str = DEFAULT_SF1_TABLE,
    tickers_table: str = DEFAULT_TICKERS_TABLE,
    universe_table: str = DEFAULT_UNIVERSE_TABLE,
    source_start_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    horizons: tuple[int, ...] = (21, 5),
) -> pd.DataFrame:
    clean_buckets = parse_buckets(list(buckets))
    clean_horizons = validate_horizons(horizons)
    prices = load_price_panel(
        conn,
        tickers=tickers,
        source_table=source_table,
        start_date=source_start_date,
        end_date=end_date,
    )
    panel = build_target_base(
        prices,
        panel_name=panel_name,
        horizons=clean_horizons,
    )
    panel = add_ticker_metadata(
        panel,
        load_ticker_metadata(conn, tickers=tickers, tickers_table=tickers_table),
    )
    panel = apply_feature_buckets(
        conn,
        panel,
        tickers=tickers,
        buckets=clean_buckets,
        end_date=end_date,
        spy_table=spy_table,
        daily_table=daily_table,
        sf1_table=sf1_table,
        source_start_date=source_start_date,
    )
    panel = filter_output_dates(panel, start_date=start_date, end_date=end_date)
    if panel_name == "universe_fastai_v1":
        panel = filter_to_universe_membership(
            panel,
            load_universe_membership(
                conn,
                tickers=tickers,
                universe_table=universe_table,
                start_date=start_date,
                end_date=end_date,
            ),
        )
    if panel[["ticker", "date"]].duplicated().any():
        raise ValueError("factor panel contains duplicate ticker/date rows")
    return panel


def write_factor_panel_table(
    conn: duckdb.DuckDBPyConnection,
    panel: pd.DataFrame,
    output_table: str = DEFAULT_OUTPUT_TABLE,
) -> int:
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE {quote_identifier(output_table)} AS
        SELECT * FROM panel
        """
    )
    return conn.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(output_table)}"
    ).fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a bucketed multi-factor experiment panel",
    )
    parser.add_argument("--db", required=True, help="Path to DuckDB database")
    parser.add_argument(
        "--panel",
        default=DEFAULT_PANEL,
        choices=("large_cap_fixed", "universe_fastai_v1"),
        help=f"Named panel to build (default: {DEFAULT_PANEL})",
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        help="Optional ticker override or universe subset",
    )
    parser.add_argument(
        "--buckets",
        nargs="+",
        default=list(DEFAULT_BUCKETS),
        help=f"Buckets to build, comma or space separated (default: {' '.join(DEFAULT_BUCKETS)})",
    )
    parser.add_argument("--start-date", default=None, help="Optional output start date")
    parser.add_argument(
        "--source-start-date",
        default=None,
        help=(
            "Optional earliest source date to load before output filtering; use "
            "for warmup-bounded universe builds"
        ),
    )
    parser.add_argument("--end-date", default=None, help="Optional source/output end date")
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
        "--daily-table",
        default=DEFAULT_DAILY_TABLE,
        help=f"Daily valuation source table (default: {DEFAULT_DAILY_TABLE})",
    )
    parser.add_argument(
        "--sf1-table",
        default=DEFAULT_SF1_TABLE,
        help=f"SF1 source table (default: {DEFAULT_SF1_TABLE})",
    )
    parser.add_argument(
        "--tickers-table",
        default=DEFAULT_TICKERS_TABLE,
        help=f"Ticker metadata source table (default: {DEFAULT_TICKERS_TABLE})",
    )
    parser.add_argument(
        "--universe-table",
        default=DEFAULT_UNIVERSE_TABLE,
        help=f"Universe table for explicit universe builds (default: {DEFAULT_UNIVERSE_TABLE})",
    )
    parser.add_argument(
        "--output-table",
        default=DEFAULT_OUTPUT_TABLE,
        help=f"Output table to replace (default: {DEFAULT_OUTPUT_TABLE})",
    )
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[21, 5],
        help="Forward target horizons in trading rows (default: 21 5)",
    )
    args = parser.parse_args()

    buckets = parse_buckets(args.buckets)
    horizons = validate_horizons(tuple(args.horizons))
    conn = duckdb.connect(args.db)
    try:
        selected_tickers = resolve_panel_tickers(
            conn,
            panel=args.panel,
            tickers=args.tickers,
            universe_table=args.universe_table,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        panel = build_factor_panel(
            conn,
            tickers=selected_tickers,
            panel_name=args.panel,
            buckets=buckets,
            source_table=args.source_table,
            spy_table=args.spy_table,
            daily_table=args.daily_table,
            sf1_table=args.sf1_table,
            tickers_table=args.tickers_table,
            universe_table=args.universe_table,
            source_start_date=args.source_start_date,
            start_date=args.start_date,
            end_date=args.end_date,
            horizons=horizons,
        )
        rows_written = write_factor_panel_table(
            conn,
            panel,
            output_table=args.output_table,
        )
    finally:
        conn.close()

    logger.info(
        "Wrote %s factor rows for panel %s with buckets %s to %s",
        f"{rows_written:,}",
        args.panel,
        ", ".join(buckets),
        args.output_table,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
