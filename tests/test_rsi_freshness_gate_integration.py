from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from scripts.experiments import run_rsi_experiment


def seed_source(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE sep_base (ticker VARCHAR, date DATE, closeadj DOUBLE)")
    start = date(2026, 1, 1)
    rows = []
    for offset in range(80):
        cycle = offset % 10
        closeadj = 100.0 + cycle * 2.0 if cycle < 5 else 110.0 - (cycle - 5) * 2.0
        rows.append(("AAPL", start + timedelta(days=offset), closeadj))
    conn.executemany("INSERT INTO sep_base VALUES (?, ?, ?)", rows)


def run_fixture_experiment(db_path, metrics_path, skip_freshness_check=False):
    return run_rsi_experiment.run_experiment(
        db_path=db_path,
        ticker="AAPL",
        train_end="2026-02-20",
        validation_end="2026-03-05",
        test_end="2026-03-21",
        embargo=0,
        metrics_json=metrics_path,
        skip_freshness_check=skip_freshness_check,
    )


def test_freshness_failure_message_names_stale_source_table() -> None:
    with pytest.raises(RuntimeError, match="SEP"):
        run_rsi_experiment.raise_if_freshness_failed(
            {
                "passed": False,
                "blockers": ["SEP is 3 day(s) behind API max 2026-06-12"],
            }
        )


def test_temp_db_run_does_not_call_source_freshness_gate(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "temp-rsi.duckdb"
    metrics_path = tmp_path / "metrics.json"
    conn = duckdb.connect(str(db_path))
    try:
        seed_source(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        run_rsi_experiment,
        "run_source_freshness_gate",
        lambda db_path: (_ for _ in ()).throw(
            AssertionError("temp DB should not call source freshness gate")
        ),
    )

    result = run_fixture_experiment(db_path, metrics_path)

    assert result["rows_written"] == 80
    assert metrics_path.exists()


def test_real_project_db_freshness_failure_blocks_run(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "kairos-fastai.duckdb"
    metrics_path = tmp_path / "blocked-metrics.json"
    conn = duckdb.connect(str(db_path))
    try:
        seed_source(conn)
    finally:
        conn.close()

    monkeypatch.setattr(run_rsi_experiment, "REAL_DB_PATH", db_path)
    monkeypatch.setattr(
        run_rsi_experiment,
        "run_source_freshness_gate",
        lambda db_path: (_ for _ in ()).throw(
            RuntimeError("Source freshness gate failed: SEP failed with status check_failed")
        ),
    )

    with pytest.raises(RuntimeError, match="SEP"):
        run_fixture_experiment(db_path, metrics_path)

    assert not metrics_path.exists()


def test_skip_freshness_check_allows_controlled_real_path_fixture(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "kairos-fastai.duckdb"
    metrics_path = tmp_path / "skip-metrics.json"
    conn = duckdb.connect(str(db_path))
    try:
        seed_source(conn)
    finally:
        conn.close()

    monkeypatch.setattr(run_rsi_experiment, "REAL_DB_PATH", db_path)
    monkeypatch.setattr(
        run_rsi_experiment,
        "run_source_freshness_gate",
        lambda db_path: (_ for _ in ()).throw(
            AssertionError("skip should bypass source freshness gate")
        ),
    )

    result = run_fixture_experiment(
        db_path,
        metrics_path,
        skip_freshness_check=True,
    )

    assert result["rows_written"] == 80
    assert metrics_path.exists()
