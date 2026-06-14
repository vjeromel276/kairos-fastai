from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb

from scripts.experiments import train_rsi_one_ticker_baselines as trainer


def seed_feature_set_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE rsi_experiment_one_ticker_v1 (
            ticker VARCHAR,
            date DATE,
            closeadj DOUBLE,
            rsi_14 DOUBLE,
            rsi_slope_3 DOUBLE,
            rsi_slope_5 DOUBLE,
            rsi_slope_10 DOUBLE,
            rsi_slope_20 DOUBLE,
            rsi_ema_5 DOUBLE,
            rsi_ema_10 DOUBLE,
            rsi_ema_20 DOUBLE,
            rsi_ema_5_minus_10 DOUBLE,
            rsi_ema_5_minus_20 DOUBLE,
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
        rsi_ema_5 = rsi + 1.0
        rsi_ema_10 = rsi - 1.0
        rsi_ema_20 = rsi - 2.0
        rows.append(
            (
                "AAPL",
                trading_date,
                100.0 + offset,
                rsi,
                rsi - 50.0,
                rsi - 48.0,
                rsi - 46.0,
                rsi - 44.0,
                rsi_ema_5,
                rsi_ema_10,
                rsi_ema_20,
                rsi_ema_5 - rsi_ema_10,
                rsi_ema_5 - rsi_ema_20,
                future_return,
                winner,
            )
        )
    conn.executemany(
        """
        INSERT INTO rsi_experiment_one_ticker_v1
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def test_feature_set_comparison_uses_same_splits_and_targets(tmp_path) -> None:
    db_path = tmp_path / "rsi-feature-comparison.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_feature_set_table(conn)
        summary = trainer.run_feature_set_comparison(
            conn,
            ticker="AAPL",
            train_end="2026-01-12",
            validation_end="2026-01-20",
            test_end="2026-01-30",
            embargo=0,
        )
    finally:
        conn.close()

    assert set(summary["feature_sets"]) == {"A", "B", "C", "D"}
    assert summary["feature_sets"]["A"]["regression"]["feature_columns"] == ["rsi_14"]
    assert summary["feature_sets"]["B"]["regression"]["feature_columns"] == [
        "rsi_14",
        "rsi_slope_3",
        "rsi_slope_5",
        "rsi_slope_10",
        "rsi_slope_20",
    ]
    assert summary["feature_sets"]["C"]["regression"]["feature_columns"] == [
        "rsi_14",
        "rsi_ema_5",
        "rsi_ema_10",
        "rsi_ema_20",
        "rsi_ema_5_minus_10",
        "rsi_ema_5_minus_20",
    ]
    assert summary["feature_sets"]["D"]["regression"]["feature_columns"] == [
        "rsi_14",
        "rsi_slope_3",
        "rsi_slope_5",
        "rsi_slope_10",
        "rsi_slope_20",
        "rsi_ema_5",
        "rsi_ema_10",
        "rsi_ema_20",
        "rsi_ema_5_minus_10",
        "rsi_ema_5_minus_20",
    ]

    regression_targets = {
        result["regression"]["target"]
        for result in summary["feature_sets"].values()
    }
    classification_targets = {
        result["classification"]["target"]
        for result in summary["feature_sets"].values()
    }
    assert regression_targets == {"future_5d_return"}
    assert classification_targets == {"winner_5d"}

    regression_split_ranges = [
        result["regression"]["split_ranges"]
        for result in summary["feature_sets"].values()
    ]
    assert all(split_range == regression_split_ranges[0] for split_range in regression_split_ranges)

    comparison = summary["validation_comparison"]
    assert set(comparison["regression_rmse"]["values"]) == {"A", "B", "C", "D"}
    assert set(comparison["regression_rmse"]["improves_over_a"]) == {"B", "C", "D"}
    assert set(comparison["classification_auc"]["values"]) == {"A", "B", "C", "D"}
    assert set(comparison["classification_auc"]["improves_over_a"]) == {"B", "C", "D"}


def test_feature_set_all_cli_writes_comparable_metrics(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "rsi-feature-comparison-cli.duckdb"
    metrics_path = tmp_path / "metrics.json"
    conn = duckdb.connect(str(db_path))
    try:
        seed_feature_set_table(conn)
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
            "--feature-set",
            "ALL",
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
    assert set(summary["feature_sets"]) == {"A", "B", "C", "D"}
    assert "validation_comparison" in summary
    assert "best_feature_set" in summary["validation_comparison"]["regression_rmse"]
