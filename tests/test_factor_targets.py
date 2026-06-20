from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from scripts.experiments import build_factor_targets as targets


def seed_price_source(conn: duckdb.DuckDBPyConnection) -> list[date]:
    conn.execute(
        """
        CREATE TABLE sep_base (
            ticker VARCHAR,
            date DATE,
            close DOUBLE,
            closeadj DOUBLE
        )
        """
    )
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=offset) for offset in range(30)]
    rows = []
    for offset, trading_date in enumerate(dates):
        rows.append(("AAPL", trading_date, 1000.0 + offset, 100.0 + offset))
        rows.append(("MSFT", trading_date, 2000.0 - offset, 200.0 - offset))
    conn.executemany("INSERT INTO sep_base VALUES (?, ?, ?, ?)", rows)
    return dates


def test_build_factor_targets_uses_adjusted_prices_and_ticker_boundaries(tmp_path) -> None:
    db_path = tmp_path / "factor-targets.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        dates = seed_price_source(conn)
        panel = targets.build_factor_targets(
            conn,
            tickers=["AAPL", "MSFT"],
            horizons=(21, 5),
        )
    finally:
        conn.close()

    assert len(panel) == 60
    assert panel[["ticker", "date"]].drop_duplicates().shape[0] == len(panel)
    assert panel["panel_name"].unique().tolist() == ["large_cap_fixed"]
    assert panel["ticker"].unique().tolist() == ["AAPL", "MSFT"]

    aapl = panel[panel["ticker"] == "AAPL"].reset_index(drop=True)
    msft = panel[panel["ticker"] == "MSFT"].reset_index(drop=True)
    assert aapl["date"].tolist() == pd.to_datetime(dates).tolist()
    assert msft["date"].tolist() == pd.to_datetime(dates).tolist()

    assert aapl["future_21d_return"].iloc[0] == pytest.approx(121.0 / 100.0 - 1.0)
    assert aapl["future_5d_return"].iloc[0] == pytest.approx(105.0 / 100.0 - 1.0)
    assert msft["future_21d_return"].iloc[0] == pytest.approx(179.0 / 200.0 - 1.0)
    assert msft["future_5d_return"].iloc[0] == pytest.approx(195.0 / 200.0 - 1.0)

    assert aapl["winner_21d"].iloc[0] == 1
    assert aapl["winner_5d"].iloc[0] == 1
    assert msft["winner_21d"].iloc[0] == 0
    assert msft["winner_5d"].iloc[0] == 0

    assert aapl["future_21d_return"].iloc[-21:].isna().all()
    assert msft["future_21d_return"].iloc[-21:].isna().all()
    assert aapl["winner_21d"].iloc[-21:].isna().all()
    assert msft["winner_21d"].iloc[-21:].isna().all()
    assert aapl["future_5d_return"].iloc[-5:].isna().all()
    assert msft["future_5d_return"].iloc[-5:].isna().all()
    assert aapl["winner_5d"].iloc[-5:].isna().all()
    assert msft["winner_5d"].iloc[-5:].isna().all()


def test_factor_targets_add_prior_return_baselines(tmp_path) -> None:
    db_path = tmp_path / "factor-target-priors.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_price_source(conn)
        panel = targets.build_factor_targets(
            conn,
            tickers=["AAPL"],
            horizons=(21, 5),
        )
    finally:
        conn.close()

    assert panel["prior_21d_return"].iloc[:21].isna().all()
    assert panel["prior_5d_return"].iloc[:5].isna().all()
    assert panel["prior_21d_return"].iloc[21] == pytest.approx(121.0 / 100.0 - 1.0)
    assert panel["prior_5d_return"].iloc[5] == pytest.approx(105.0 / 100.0 - 1.0)


def test_factor_target_cli_writes_output_table_with_filters(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "factor-target-cli.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_price_source(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        targets.sys,
        "argv",
        [
            "build_factor_targets.py",
            "--db",
            str(db_path),
            "--tickers",
            "aapl",
            "MSFT",
            "--start-date",
            "2026-01-03",
            "--end-date",
            "2026-01-12",
            "--panel-name",
            "unit_test_panel",
            "--output-table",
            "factor_targets_test",
        ],
    )

    assert targets.main() == 0

    conn = duckdb.connect(str(db_path))
    try:
        output = conn.execute(
            """
            SELECT *
            FROM factor_targets_test
            ORDER BY ticker, date
            """
        ).fetchdf()
    finally:
        conn.close()

    assert len(output) == 20
    assert output["ticker"].unique().tolist() == ["AAPL", "MSFT"]
    assert output["panel_name"].unique().tolist() == ["unit_test_panel"]
    assert output["date"].min() == pd.Timestamp("2026-01-03")
    assert output["date"].max() == pd.Timestamp("2026-01-12")
    assert {"future_21d_return", "winner_21d", "future_5d_return", "winner_5d"}.issubset(
        output.columns
    )


def test_factor_targets_reject_invalid_horizons() -> None:
    with pytest.raises(ValueError, match="target horizons must be >= 1"):
        targets.validate_horizons((21, 0))
