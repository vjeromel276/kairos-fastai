from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from scripts.experiments.build_universe_price_regime_panel import (
    build_universe_price_regime_panel,
)


def seed_sources(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE sep_base (
            ticker VARCHAR,
            date DATE,
            closeadj DOUBLE,
            volume DOUBLE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sfp (
            ticker VARCHAR,
            date DATE,
            closeadj DOUBLE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE tickers (
            ticker VARCHAR,
            exchange VARCHAR,
            sector VARCHAR,
            industry VARCHAR,
            lastupdated DATE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE universe_fastai_v1 (
            ticker VARCHAR,
            date DATE
        )
        """
    )

    start = date(2026, 1, 1)
    sep_rows = []
    spy_rows = []
    for offset in range(30):
        trading_date = start + timedelta(days=offset)
        sep_rows.append(("AAPL", trading_date, 100.0 + offset, 1000.0 + offset))
        sep_rows.append(("MSFT", trading_date, 200.0 + offset * 2.0, 2000.0 + offset))
        spy_rows.append(("SPY", trading_date, 400.0 + offset))

    conn.executemany("INSERT INTO sep_base VALUES (?, ?, ?, ?)", sep_rows)
    conn.executemany("INSERT INTO sfp VALUES (?, ?, ?)", spy_rows)
    conn.executemany(
        "INSERT INTO tickers VALUES (?, ?, ?, ?, ?)",
        [
            ("AAPL", "NASDAQ", "Technology", "Consumer Electronics", start),
            ("MSFT", "NASDAQ", "Technology", "Software", start),
        ],
    )
    conn.executemany(
        "INSERT INTO universe_fastai_v1 VALUES (?, ?)",
        [
            ("MSFT", date(2026, 1, 10)),
            ("AAPL", date(2026, 1, 11)),
        ],
    )


def test_build_universe_price_regime_panel_filters_to_membership_dates(tmp_path) -> None:
    db_path = tmp_path / "universe-price-regime.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_sources(conn)
        rows_written = build_universe_price_regime_panel(
            conn,
            output_table="factor_panel_test",
            source_start_date="2026-01-01",
            start_date="2026-01-10",
        )
        panel = conn.execute(
            """
            SELECT *
            FROM factor_panel_test
            ORDER BY ticker, date
            """
        ).fetchdf()
    finally:
        conn.close()

    assert rows_written == 2
    aapl = panel[panel["ticker"] == "AAPL"].iloc[0]
    msft = panel[panel["ticker"] == "MSFT"].iloc[0]
    assert panel["ticker"].tolist() == ["AAPL", "MSFT"]
    assert str(aapl["date"])[:10] == "2026-01-11"
    assert str(msft["date"])[:10] == "2026-01-10"
    assert msft["px_return_5d"] == pytest.approx(218.0 / 208.0 - 1.0)
    assert msft["future_5d_return"] == pytest.approx(228.0 / 218.0 - 1.0)
    assert set(panel["panel_name"]) == {"universe_fastai_v1"}
