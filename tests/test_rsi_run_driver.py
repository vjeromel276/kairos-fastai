from __future__ import annotations

from datetime import date, timedelta

import duckdb
import json

from scripts.experiments import run_rsi_experiment


def seed_driver_source(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE sep_base (ticker VARCHAR, date DATE, closeadj DOUBLE)")
    start = date(2026, 1, 1)
    rows = []
    for offset in range(80):
        cycle = offset % 10
        if cycle < 5:
            closeadj = 100.0 + cycle * 2.0
        else:
            closeadj = 110.0 - (cycle - 5) * 2.0
        rows.append(("AAPL", start + timedelta(days=offset), closeadj))
    conn.executemany("INSERT INTO sep_base VALUES (?, ?, ?)", rows)


def test_rsi_run_driver_builds_dataset_and_writes_metrics(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    db_path = tmp_path / "rsi-driver.duckdb"
    metrics_path = tmp_path / "metrics" / "aapl.json"
    conn = duckdb.connect(str(db_path))
    try:
        seed_driver_source(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        run_rsi_experiment.sys,
        "argv",
        [
            "run_rsi_experiment.py",
            "--db",
            str(db_path),
            "--ticker",
            "AAPL",
            "--train-end",
            "2026-02-20",
            "--validation-end",
            "2026-03-05",
            "--test-end",
            "2026-03-21",
            "--embargo",
            "0",
            "--metrics-json",
            str(metrics_path),
        ],
    )

    assert run_rsi_experiment.main() == 0
    output = capsys.readouterr().out

    assert "Output table: rsi_experiment_one_ticker_v1" in output
    assert f"Metrics JSON: {metrics_path}" in output
    assert metrics_path.exists()

    summary = json.loads(metrics_path.read_text())
    assert set(summary["feature_sets"]) == {"A", "B", "C", "D"}

    conn = duckdb.connect(str(db_path))
    try:
        columns = [
            column[1]
            for column in conn.execute(
                "PRAGMA table_info('rsi_experiment_one_ticker_v1')"
            ).fetchall()
        ]
        row_count = conn.execute(
            "SELECT COUNT(*) FROM rsi_experiment_one_ticker_v1"
        ).fetchone()[0]
    finally:
        conn.close()

    assert row_count == 80
    assert "rsi_slope_20" in columns
    assert "rsi_ema_5_minus_20" in columns
