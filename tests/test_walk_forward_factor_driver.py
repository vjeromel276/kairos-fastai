from __future__ import annotations

from datetime import date, timedelta

import duckdb

from scripts.experiments import walk_forward_factor_driver as walk_forward


def seed_walk_forward_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE factor_panel_v1 (
            ticker VARCHAR,
            date DATE,
            panel_name VARCHAR,
            px_signal DOUBLE,
            future_21d_return DOUBLE,
            winner_21d BIGINT,
            prior_21d_return DOUBLE
        )
        """
    )
    start = date(2026, 1, 1)
    specs = [
        ("AAPL", 1.0, 0.03, 0.01),
        ("MSFT", 0.0, 0.00, 0.00),
        ("JPM", -1.0, -0.02, -0.01),
    ]
    rows = []
    for offset in range(10):
        trading_date = start + timedelta(days=offset)
        for ticker, signal, future_return, prior_return in specs:
            rows.append(
                (
                    ticker,
                    trading_date,
                    "unit",
                    signal,
                    future_return,
                    int(future_return > 0),
                    prior_return,
                )
            )
    conn.executemany("INSERT INTO factor_panel_v1 VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


def test_make_walk_forward_folds_are_chronological() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(10)]

    folds = walk_forward.make_walk_forward_folds(
        dates,
        train_size=4,
        validation_size=2,
        test_size=2,
        step_size=2,
    )

    assert len(folds) == 2
    assert folds[0] == {
        "train_start": "2026-01-01",
        "train_end": "2026-01-04",
        "validation_start": "2026-01-05",
        "validation_end": "2026-01-06",
        "test_start": "2026-01-07",
        "test_end": "2026-01-08",
    }
    assert folds[1]["train_start"] == "2026-01-03"
    assert folds[1]["train_end"] < folds[1]["validation_start"]
    assert folds[1]["validation_end"] < folds[1]["test_start"]


def test_walk_forward_evaluation_records_folds_and_aggregates_metrics(tmp_path) -> None:
    db_path = tmp_path / "walk-forward.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_walk_forward_table(conn)
        report = walk_forward.run_walk_forward_factor_evaluation(
            conn,
            buckets=("price",),
            train_size=4,
            validation_size=2,
            test_size=2,
            step_size=2,
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    assert report["mode"] == "walk_forward_factor_evaluation"
    assert report["fold_count"] == 2
    assert report["folds"][0]["ranges"]["train_end"] == "2026-01-04"
    assert report["folds"][0]["ranges"]["test_end"] == "2026-01-08"
    assert report["folds"][1]["ranges"]["train_end"] == "2026-01-06"
    aggregate = report["aggregate_metrics"]["price_behavior"]
    assert aggregate["validation"]["fold_count"] == 2
    assert aggregate["test"]["mean_top_k_average_return"] == 0.03


def test_walk_forward_cli_prints_report(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "walk-forward-cli.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_walk_forward_table(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        walk_forward.sys,
        "argv",
        [
            "walk_forward_factor_driver.py",
            "--db",
            str(db_path),
            "--buckets",
            "price",
            "--train-size",
            "4",
            "--validation-size",
            "2",
            "--test-size",
            "2",
            "--step-size",
            "2",
            "--embargo",
            "0",
            "--top-k",
            "1",
        ],
    )

    assert walk_forward.main() == 0
    output = capsys.readouterr().out
    assert "Walk-forward factor evaluation report" in output
    assert '"fold_count": 2' in output
