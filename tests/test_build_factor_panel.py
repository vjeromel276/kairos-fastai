from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from scripts.experiments import build_factor_panel as panel_builder


def seed_panel_sources(conn: duckdb.DuckDBPyConnection) -> list[date]:
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
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=offset) for offset in range(30)]
    rows = []
    for offset, trading_date in enumerate(dates):
        rows.append(("AAPL", trading_date, 100.0 + offset, 1000.0 + offset))
        rows.append(("MSFT", trading_date, 200.0 + offset * 2.0, 2000.0 + offset))
    conn.executemany("INSERT INTO sep_base VALUES (?, ?, ?, ?)", rows)
    return dates


def test_build_factor_panel_with_one_bucket_and_date_filters(tmp_path) -> None:
    db_path = tmp_path / "factor-panel-one.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_sources(conn)
        panel = panel_builder.build_factor_panel(
            conn,
            tickers=["AAPL"],
            buckets=("price",),
            start_date="2026-01-05",
            end_date="2026-01-20",
        )
    finally:
        conn.close()

    assert len(panel) == 16
    assert panel[["ticker", "date"]].drop_duplicates().shape[0] == len(panel)
    assert panel["panel_name"].unique().tolist() == ["large_cap_fixed"]
    assert panel["date"].min() == pd.Timestamp("2026-01-05")
    assert panel["date"].max() == pd.Timestamp("2026-01-20")
    assert {"future_21d_return", "winner_21d", "px_return_1d"}.issubset(panel.columns)
    first_row = panel.iloc[0]
    assert first_row["px_return_1d"] == pytest.approx(104.0 / 103.0 - 1.0)


def test_build_factor_panel_uses_source_start_as_hidden_warmup(tmp_path) -> None:
    db_path = tmp_path / "factor-panel-source-start.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_sources(conn)
        panel = panel_builder.build_factor_panel(
            conn,
            tickers=["AAPL"],
            buckets=("price",),
            source_start_date="2026-01-05",
            start_date="2026-01-10",
            end_date="2026-01-20",
        )
    finally:
        conn.close()

    assert panel["date"].min() == pd.Timestamp("2026-01-10")
    first_row = panel.iloc[0]
    assert first_row["px_return_5d"] == pytest.approx(109.0 / 104.0 - 1.0)


def test_build_factor_panel_with_multiple_buckets(tmp_path) -> None:
    db_path = tmp_path / "factor-panel-multi.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_sources(conn)
        panel = panel_builder.build_factor_panel(
            conn,
            tickers=["AAPL", "MSFT"],
            buckets=("price", "volume"),
            end_date="2026-01-25",
        )
    finally:
        conn.close()

    assert panel[["ticker", "date"]].drop_duplicates().shape[0] == len(panel)
    assert {"px_return_1d", "liq_dollar_volume", "liq_adv_20d"}.issubset(panel.columns)
    aapl = panel[panel["ticker"] == "AAPL"].reset_index(drop=True)
    assert aapl["liq_dollar_volume"].iloc[0] == pytest.approx(100.0 * 1000.0)
    assert aapl["liq_adv_20d"].iloc[19] == pytest.approx(
        sum((100.0 + offset) * (1000.0 + offset) for offset in range(20)) / 20.0
    )


def test_build_factor_panel_carries_static_ticker_metadata(tmp_path) -> None:
    db_path = tmp_path / "factor-panel-metadata.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_sources(conn)
        conn.execute(
            """
            CREATE TABLE tickers (
                ticker VARCHAR,
                exchange VARCHAR,
                sector VARCHAR,
                industry VARCHAR
            )
            """
        )
        conn.executemany(
            "INSERT INTO tickers VALUES (?, ?, ?, ?)",
            [
                ("AAPL", "NASDAQ", "Technology", "Consumer Electronics"),
                ("MSFT", "NASDAQ", "Technology", "Software"),
            ],
        )
        panel = panel_builder.build_factor_panel(
            conn,
            tickers=["AAPL", "MSFT"],
            buckets=("price",),
            end_date="2026-01-10",
        )
    finally:
        conn.close()

    assert {"exchange", "sector", "industry"}.issubset(panel.columns)
    metadata = (
        panel[["ticker", "exchange", "sector", "industry"]]
        .drop_duplicates()
        .sort_values("ticker")
        .to_dict("records")
    )
    assert metadata == [
        {
            "ticker": "AAPL",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "industry": "Consumer Electronics",
        },
        {
            "ticker": "MSFT",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "industry": "Software",
        },
    ]


def test_factor_panel_cli_writes_output_table_with_default_constrained_panel(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "factor-panel-cli.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_sources(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        panel_builder.sys,
        "argv",
        [
            "build_factor_panel.py",
            "--db",
            str(db_path),
            "--buckets",
            "price,volume",
            "--end-date",
            "2026-01-10",
            "--output-table",
            "factor_panel_test",
        ],
    )

    assert panel_builder.main() == 0

    conn = duckdb.connect(str(db_path))
    try:
        output = conn.execute(
            """
            SELECT *
            FROM factor_panel_test
            ORDER BY ticker, date
            """
        ).fetchdf()
    finally:
        conn.close()

    assert output["ticker"].unique().tolist() == ["AAPL", "MSFT"]
    assert output["panel_name"].unique().tolist() == ["large_cap_fixed"]
    assert {"px_return_1d", "liq_dollar_volume"}.issubset(output.columns)


def test_universe_panel_must_be_explicit_and_reads_universe_table(tmp_path) -> None:
    db_path = tmp_path / "factor-panel-universe.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_sources(conn)
        conn.execute(
            """
            CREATE TABLE universe_fastai_v1 (
                ticker VARCHAR,
                date DATE
            )
            """
        )
        conn.execute("INSERT INTO universe_fastai_v1 VALUES ('MSFT', DATE '2026-01-10')")

        default_tickers = panel_builder.resolve_panel_tickers(
            conn,
            panel="large_cap_fixed",
            tickers=["AAPL"],
        )
        universe_tickers = panel_builder.resolve_panel_tickers(
            conn,
            panel="universe_fastai_v1",
            tickers=None,
        )
        panel = panel_builder.build_factor_panel(
            conn,
            tickers=universe_tickers,
            panel_name="universe_fastai_v1",
            buckets=("price",),
            end_date="2026-01-10",
        )
    finally:
        conn.close()

    assert default_tickers == ["AAPL"]
    assert universe_tickers == ["MSFT"]
    assert len(panel) == 1
    assert panel["ticker"].unique().tolist() == ["MSFT"]
    assert panel["date"].tolist() == [pd.Timestamp("2026-01-10")]
    assert panel["panel_name"].unique().tolist() == ["universe_fastai_v1"]


def test_factor_panel_rejects_unsupported_bucket() -> None:
    with pytest.raises(ValueError, match="unsupported buckets"):
        panel_builder.parse_buckets(["price", "unknown"])
