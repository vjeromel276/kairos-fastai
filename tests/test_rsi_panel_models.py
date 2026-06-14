from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from scripts.experiments import train_rsi_one_ticker_baselines as trainer


def seed_panel_model_table(conn: duckdb.DuckDBPyConnection, duplicate: bool = False) -> None:
    conn.execute(
        """
        CREATE TABLE rsi_experiment_panel_v1 (
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
    ticker_specs = [
        ("AAPL", 30.0, -0.02),
        ("MSFT", 50.0, 0.00),
        ("GOOG", 70.0, 0.02),
    ]
    rows = []
    for offset in range(8):
        trading_date = start + timedelta(days=offset)
        for ticker, rsi, future_return in ticker_specs:
            rows.append(
                (
                    ticker,
                    trading_date,
                    100.0 + offset + rsi / 100.0,
                    rsi,
                    rsi - 50.0,
                    rsi - 48.0,
                    rsi - 46.0,
                    rsi - 44.0,
                    rsi + 1.0,
                    rsi - 1.0,
                    rsi - 2.0,
                    2.0,
                    3.0,
                    future_return,
                    int(future_return > 0),
                )
            )
    if duplicate:
        rows.append(rows[0])
    conn.executemany(
        "INSERT INTO rsi_experiment_panel_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def test_ranking_metrics_are_calculated_by_date_then_aggregated() -> None:
    dates = pd.Series(
        [
            date(2026, 1, 1),
            date(2026, 1, 1),
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 2),
            date(2026, 1, 2),
        ]
    )
    actual = pd.Series([0.10, -0.10, 0.05, -0.02, 0.03, 0.01])
    predicted = pd.Series([0.9, 0.1, 0.8, 0.2, 0.7, 0.6])

    metrics = trainer.ranking_metrics_by_date(actual, predicted, dates, top_k=2)

    assert metrics["date_count"] == 2
    assert metrics["top_k"] == 2
    assert metrics["top_k_average_return"] == pytest.approx(((0.10 + 0.05) / 2 + (0.03 + 0.01) / 2) / 2)
    assert metrics["top_k_win_rate"] == pytest.approx(1.0)
    assert metrics["mean_information_coefficient"] == pytest.approx(1.0)


def test_panel_models_use_global_date_splits_and_ranking_metrics(tmp_path) -> None:
    db_path = tmp_path / "rsi-panel-models.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_model_table(conn)
        summary = trainer.run_panel_models(
            conn,
            tickers=["AAPL", "MSFT", "GOOG"],
            table_name="rsi_experiment_panel_v1",
            feature_set="A",
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    assert summary["mode"] == "panel"
    assert summary["tickers"] == ["AAPL", "GOOG", "MSFT"]
    assert summary["regression"]["split_ranges"]["train"]["rows"] == 12
    assert summary["regression"]["split_ranges"]["validation"]["rows"] == 6
    assert summary["regression"]["split_ranges"]["test"]["rows"] == 6
    assert summary["regression"]["split_ranges"] == summary["classification"]["split_ranges"]

    validation_ranking = summary["regression"]["metrics"]["validation"]["ranking"]
    test_ranking = summary["classification"]["metrics"]["test"]["ranking"]
    assert validation_ranking["date_count"] == 2
    assert validation_ranking["top_k_average_return"] == pytest.approx(0.02)
    assert validation_ranking["top_k_win_rate"] == pytest.approx(1.0)
    assert validation_ranking["mean_information_coefficient"] == pytest.approx(1.0)
    assert test_ranking["top_k_average_return"] == pytest.approx(0.02)
    assert test_ranking["top_k_win_rate"] == pytest.approx(1.0)


def test_panel_models_accept_combined_feature_set_d(tmp_path) -> None:
    db_path = tmp_path / "rsi-panel-models-d.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_model_table(conn)
        summary = trainer.run_panel_models(
            conn,
            tickers=["AAPL", "MSFT", "GOOG"],
            table_name="rsi_experiment_panel_v1",
            feature_set="D",
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    assert summary["feature_set"] == "D"
    assert summary["regression"]["feature_columns"] == [
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
    assert summary["regression"]["split_ranges"] == summary["classification"]["split_ranges"]


def test_panel_models_reject_duplicate_ticker_dates(tmp_path) -> None:
    db_path = tmp_path / "rsi-panel-duplicates.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_panel_model_table(conn, duplicate=True)
        with pytest.raises(ValueError, match="duplicate ticker/date"):
            trainer.run_panel_models(
                conn,
                tickers=["AAPL", "MSFT", "GOOG"],
                table_name="rsi_experiment_panel_v1",
                feature_set="A",
                train_end="2026-01-04",
                validation_end="2026-01-06",
                test_end="2026-01-08",
                embargo=0,
                top_k=1,
            )
    finally:
        conn.close()
