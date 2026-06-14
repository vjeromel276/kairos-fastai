from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb

from scripts.experiments import train_rsi_one_ticker_baselines as trainer


def seed_rsi_experiment_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE rsi_experiment_one_ticker_v1 (
            ticker VARCHAR,
            date DATE,
            closeadj DOUBLE,
            rsi_14 DOUBLE,
            future_5d_return DOUBLE,
            winner_5d BIGINT
        )
        """
    )
    start = date(2026, 1, 1)
    rows = []
    for offset in range(30):
        trading_date = start + timedelta(days=offset)
        rsi = 40.0 if offset % 2 == 0 else 60.0
        future_return = None if offset >= 25 else (-0.01 if rsi < 50 else 0.01)
        winner = None if future_return is None else int(future_return > 0)
        rows.append(("AAPL", trading_date, 100.0 + offset, rsi, future_return, winner))

    rows.append(("MSFT", start, 200.0, 55.0, 0.02, 1))
    conn.executemany(
        "INSERT INTO rsi_experiment_one_ticker_v1 VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )


def test_one_ticker_baseline_cli_runs_and_writes_metrics_json(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "rsi-baselines.duckdb"
    metrics_path = tmp_path / "metrics" / "aapl.json"
    conn = duckdb.connect(str(db_path))
    try:
        seed_rsi_experiment_table(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        trainer.sys,
        "argv",
        [
            "train_rsi_one_ticker_baselines.py",
            "--db",
            str(db_path),
            "--ticker",
            "AAPL",
            "--train-end",
            "2026-01-12",
            "--validation-end",
            "2026-01-20",
            "--test-end",
            "2026-01-30",
            "--embargo",
            "0",
            "--metrics-json",
            str(metrics_path),
        ],
    )

    assert trainer.main() == 0

    summary = json.loads(metrics_path.read_text())
    assert summary["ticker"] == "AAPL"
    assert summary["regression"]["model"] == "linear_regression"
    assert summary["classification"]["model"] == "logistic_regression"
    assert summary["regression"]["feature_columns"] == ["rsi_14"]
    assert summary["classification"]["feature_columns"] == ["rsi_14"]

    regression_metrics = summary["regression"]["metrics"]
    assert set(regression_metrics["validation"]) == {
        "model",
        "mean_return_baseline",
        "prior_return_baseline",
    }
    classification_metrics = summary["classification"]["metrics"]
    assert set(classification_metrics["validation"]) == {
        "model",
        "always_up_baseline",
        "prior_return_direction_baseline",
    }

    assert summary["regression"]["prediction_counts"] == {
        "train": 0,
        "validation": 8,
        "test": 5,
    }
    assert summary["classification"]["prediction_counts"] == {
        "train": 0,
        "validation": 8,
        "test": 5,
    }
    assert summary["regression"]["split_ranges"]["train"]["max_date"] < (
        summary["regression"]["split_ranges"]["validation"]["min_date"]
    )
    assert summary["regression"]["split_ranges"]["validation"]["max_date"] < (
        summary["regression"]["split_ranges"]["test"]["min_date"]
    )


def test_run_baselines_filters_to_selected_ticker_and_complete_rows(tmp_path) -> None:
    db_path = tmp_path / "rsi-baselines-direct.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_rsi_experiment_table(conn)
        summary = trainer.run_one_ticker_baselines(
            conn,
            ticker="AAPL",
            train_end="2026-01-12",
            validation_end="2026-01-20",
            test_end="2026-01-30",
            embargo=0,
        )
    finally:
        conn.close()

    assert summary["table"] == "rsi_experiment_one_ticker_v1"
    assert summary["regression"]["split_ranges"]["train"]["rows"] == 12
    assert summary["regression"]["split_ranges"]["validation"]["rows"] == 8
    assert summary["regression"]["split_ranges"]["test"]["rows"] == 5
    assert summary["classification"]["metrics"]["test"]["model"]["count"] == 5
    assert summary["classification"]["metrics"]["test"]["always_up_baseline"]["count"] == 5
