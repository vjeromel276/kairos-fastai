from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from scripts.experiments import build_rsi_one_ticker_dataset as builder


def seed_panel_source(conn: duckdb.DuckDBPyConnection) -> list[date]:
    conn.execute("CREATE TABLE sep_base (ticker VARCHAR, date DATE, closeadj DOUBLE)")
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=offset) for offset in range(10)]
    rows = []
    for offset, trading_date in enumerate(dates):
        rows.append(("AAPL", trading_date, 100.0 + offset))
        rows.append(("MSFT", trading_date, 200.0 - offset))
    rows.append(("TSLA", dates[0], 300.0))
    conn.executemany("INSERT INTO sep_base VALUES (?, ?, ?)", rows)
    return dates


def test_build_panel_dataset_preserves_ticker_boundaries(tmp_path) -> None:
    db_path = tmp_path / "rsi-panel.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        dates = seed_panel_source(conn)
        dataset = builder.build_panel_dataset(
            conn,
            tickers=["AAPL", "MSFT"],
            rsi_window=3,
            horizon_days=2,
            feature_set="B",
        )
    finally:
        conn.close()

    assert len(dataset) == 20
    assert dataset[["ticker", "date"]].drop_duplicates().shape[0] == len(dataset)
    assert dataset["ticker"].unique().tolist() == ["AAPL", "MSFT"]

    aapl = dataset[dataset["ticker"] == "AAPL"].reset_index(drop=True)
    msft = dataset[dataset["ticker"] == "MSFT"].reset_index(drop=True)
    assert aapl["date"].tolist() == pd.to_datetime(dates).tolist()
    assert msft["date"].tolist() == pd.to_datetime(dates).tolist()

    assert aapl["future_2d_return"].iloc[0] == pytest.approx(102.0 / 100.0 - 1.0)
    assert msft["future_2d_return"].iloc[0] == pytest.approx(198.0 / 200.0 - 1.0)
    assert aapl["future_2d_return"].iloc[-2:].isna().all()
    assert msft["future_2d_return"].iloc[-2:].isna().all()

    assert aapl["rsi_3"].iloc[:3].isna().all()
    assert msft["rsi_3"].iloc[:3].isna().all()
    assert aapl["rsi_3"].iloc[3] == 100.0
    assert msft["rsi_3"].iloc[3] == 0.0
    assert aapl["rsi_slope_3"].iloc[:6].isna().all()
    assert msft["rsi_slope_3"].iloc[:6].isna().all()


def test_panel_cli_writes_default_panel_table_with_ticker_and_date_filters(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "rsi-panel-cli.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_source(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        builder.sys,
        "argv",
        [
            "build_rsi_one_ticker_dataset.py",
            "--db",
            str(db_path),
            "--tickers",
            "AAPL",
            "MSFT",
            "--start-date",
            "2026-01-03",
            "--end-date",
            "2026-01-08",
            "--rsi-window",
            "3",
            "--horizon-days",
            "2",
            "--feature-set",
            "C",
        ],
    )

    assert builder.main() == 0

    conn = duckdb.connect(str(db_path))
    try:
        output = conn.execute(
            """
            SELECT *
            FROM rsi_experiment_panel_v1
            ORDER BY ticker, date
            """
        ).fetchdf()
    finally:
        conn.close()

    assert len(output) == 12
    assert output["ticker"].unique().tolist() == ["AAPL", "MSFT"]
    assert output["date"].min() == pd.Timestamp("2026-01-03")
    assert output["date"].max() == pd.Timestamp("2026-01-08")
    assert "rsi_ema_5" in output.columns
    assert "rsi_ema_5_minus_20" in output.columns
