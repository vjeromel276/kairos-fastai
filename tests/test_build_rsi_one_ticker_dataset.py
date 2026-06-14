from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from scripts.experiments import build_rsi_one_ticker_dataset as builder


def seed_sep_base(
    conn: duckdb.DuckDBPyConnection,
    table_name: str = "sep_base",
    future_multiplier: float = 1.0,
) -> list[date]:
    conn.execute(f"CREATE TABLE {table_name} (ticker VARCHAR, date DATE, closeadj DOUBLE)")
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=offset) for offset in range(20)]

    rows = []
    for offset, trading_date in enumerate(dates):
        closeadj = 100.0 + offset
        if offset >= 15:
            closeadj *= future_multiplier
        rows.append(("AAPL", trading_date, closeadj))
    rows.extend(
        [
            ("MSFT", dates[0], 200.0),
            ("MSFT", dates[1], 201.0),
        ]
    )
    conn.executemany(f"INSERT INTO {table_name} VALUES (?, ?, ?)", rows)
    return dates


def test_cli_requires_db_and_ticker(monkeypatch) -> None:
    monkeypatch.setattr(builder.sys, "argv", ["build_rsi_one_ticker_dataset.py"])

    with pytest.raises(SystemExit) as excinfo:
        builder.main()

    assert excinfo.value.code == 2


def test_build_one_ticker_dataset_writes_default_table(tmp_path) -> None:
    db_path = tmp_path / "rsi-one-ticker.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        dates = seed_sep_base(conn)
        dataset = builder.build_one_ticker_dataset(conn, "AAPL")
        rows_written = builder.write_dataset_table(conn, dataset)

        output = conn.execute(
            """
            SELECT ticker, date, closeadj, rsi_14, future_5d_return, winner_5d
            FROM rsi_experiment_one_ticker_v1
            ORDER BY date
            """
        ).fetchdf()
    finally:
        conn.close()

    assert rows_written == 20
    assert len(output) == 20
    assert output[["ticker", "date"]].drop_duplicates().shape[0] == len(output)
    assert output["ticker"].unique().tolist() == ["AAPL"]
    assert output["date"].tolist() == pd.to_datetime(dates).tolist()
    assert output["rsi_14"].iloc[:14].isna().all()
    assert output["rsi_14"].iloc[14:].tolist() == [100.0] * 6
    assert output["future_5d_return"].iloc[0] == pytest.approx(105.0 / 100.0 - 1.0)
    assert output["future_5d_return"].iloc[-5:].isna().all()
    assert output["winner_5d"].iloc[:15].tolist() == [1] * 15
    assert output["winner_5d"].iloc[-5:].isna().all()


def test_main_runs_against_temp_duckdb_fixture(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "rsi-main.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_sep_base(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        builder.sys,
        "argv",
        [
            "build_rsi_one_ticker_dataset.py",
            "--db",
            str(db_path),
            "--ticker",
            "AAPL",
        ],
    )

    assert builder.main() == 0

    conn = duckdb.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM rsi_experiment_one_ticker_v1").fetchone()[0]
    finally:
        conn.close()

    assert count == 20


def test_rsi_features_do_not_use_future_prices(tmp_path) -> None:
    db_path = tmp_path / "rsi-no-leakage.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        dates = seed_sep_base(conn, table_name="sep_base_original")
        seed_sep_base(conn, table_name="sep_base_changed_future", future_multiplier=10.0)

        original = builder.build_one_ticker_dataset(
            conn,
            "AAPL",
            source_table="sep_base_original",
        )
        changed_future = builder.build_one_ticker_dataset(
            conn,
            "AAPL",
            source_table="sep_base_changed_future",
        )
    finally:
        conn.close()

    cutoff_date = pd.Timestamp(dates[14])
    original_known = original.loc[original["date"] <= cutoff_date, "rsi_14"].reset_index(drop=True)
    changed_known = changed_future.loc[
        changed_future["date"] <= cutoff_date, "rsi_14"
    ].reset_index(drop=True)

    pd.testing.assert_series_equal(original_known, changed_known, check_names=False)
