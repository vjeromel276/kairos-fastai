from __future__ import annotations

from datetime import date, timedelta

import duckdb

from scripts.experiments import build_rsi_one_ticker_dataset as builder
from scripts.experiments import check_rsi_dataset_quality as quality


def seed_source(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE sep_base (ticker VARCHAR, date DATE, closeadj DOUBLE)")
    start = date(2026, 1, 1)
    rows = [
        ("AAPL", start + timedelta(days=offset), 100.0 + offset)
        for offset in range(20)
    ]
    conn.executemany("INSERT INTO sep_base VALUES (?, ?, ?)", rows)


def build_fixture_dataset(db_path) -> None:
    conn = duckdb.connect(str(db_path))
    try:
        seed_source(conn)
        dataset = builder.build_one_ticker_dataset(conn, "AAPL")
        builder.write_dataset_table(conn, dataset)
    finally:
        conn.close()


def test_quality_checker_reports_valid_dataset(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "rsi-quality-valid.duckdb"
    build_fixture_dataset(db_path)

    monkeypatch.setattr(
        quality.sys,
        "argv",
        [
            "check_rsi_dataset_quality.py",
            "--db",
            str(db_path),
        ],
    )

    assert quality.main() == 0
    output = capsys.readouterr().out

    assert "Rows: 20" in output
    assert "Tickers: 1" in output
    assert "Date range: 2026-01-01 00:00:00 -> 2026-01-20 00:00:00" in output
    assert "Duplicate ticker/date keys: 0" in output
    assert "Feature null counts:" in output
    assert "rsi_14: 14" in output
    assert "Target availability:" in output
    assert "target_available_rows: 15" in output
    assert "expected_target_null_rows: 5" in output
    assert "Valid: True" in output


def test_quality_checker_fails_on_duplicate_ticker_date(tmp_path) -> None:
    db_path = tmp_path / "rsi-quality-duplicates.duckdb"
    build_fixture_dataset(db_path)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO rsi_experiment_one_ticker_v1
            SELECT *
            FROM rsi_experiment_one_ticker_v1
            WHERE date = DATE '2026-01-03'
            """
        )
        report = quality.validate_dataset_quality(conn)
    finally:
        conn.close()

    assert report["valid"] is False
    assert report["duplicate_key_count"] == 1


def test_quality_checker_fails_on_broken_future_target_alignment(tmp_path) -> None:
    db_path = tmp_path / "rsi-quality-target.duckdb"
    build_fixture_dataset(db_path)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            UPDATE rsi_experiment_one_ticker_v1
            SET future_5d_return = 0.10,
                winner_5d = 1
            WHERE date = DATE '2026-01-20'
            """
        )
        report = quality.validate_dataset_quality(conn)
    finally:
        conn.close()

    assert report["valid"] is False
    assert report["target_alignment"]["unexpected_target_values"] == 1
    assert report["target_alignment"]["unexpected_winner_values"] == 1
