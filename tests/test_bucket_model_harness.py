from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from scripts.experiments import bucket_model_harness as harness


def seed_factor_model_table(
    conn: duckdb.DuckDBPyConnection,
    include_volume: bool = True,
    all_null_volume: bool = False,
) -> None:
    volume_column = ", liq_signal DOUBLE" if include_volume else ""
    conn.execute(
        f"""
        CREATE TABLE factor_panel_v1 (
            ticker VARCHAR,
            date DATE,
            panel_name VARCHAR,
            px_signal DOUBLE
            {volume_column},
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
    for offset in range(8):
        trading_date = start + timedelta(days=offset)
        for ticker, signal, future_return, prior_return in specs:
            if include_volume:
                rows.append(
                    (
                        ticker,
                        trading_date,
                        "unit",
                        signal,
                        None if all_null_volume else signal * 10.0,
                        future_return,
                        int(future_return > 0),
                        prior_return,
                    )
                )
            else:
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
    placeholders = ", ".join(["?"] * (8 if include_volume else 7))
    conn.executemany(f"INSERT INTO factor_panel_v1 VALUES ({placeholders})", rows)


def test_bucket_only_models_use_same_global_splits_and_ranking_metrics(tmp_path) -> None:
    db_path = tmp_path / "bucket-models.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_model_table(conn)
        summary = harness.run_bucket_only_models(
            conn,
            buckets=("price", "volume"),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    assert summary["mode"] == "bucket_only"
    assert summary["global_split_ranges"]["train"]["rows"] == 12
    assert summary["global_split_ranges"]["validation"]["rows"] == 6
    assert summary["global_split_ranges"]["test"]["rows"] == 6
    assert set(summary["buckets"]) == {"price_behavior", "volume_liquidity"}

    price = summary["buckets"]["price_behavior"]
    volume = summary["buckets"]["volume_liquidity"]
    assert price["status"] == "computed"
    assert volume["status"] == "computed"
    assert price["feature_columns"] == ["px_signal"]
    assert volume["feature_columns"] == ["liq_signal"]
    assert price["complete_split_ranges"] == volume["complete_split_ranges"]

    validation = price["metrics"]["validation"]
    assert validation["ranking"]["date_count"] == 2
    assert validation["ranking"]["top_k_average_return"] == pytest.approx(0.03)
    assert validation["ranking"]["top_k_win_rate"] == pytest.approx(1.0)
    assert "baseline_ranking" in validation
    assert "top_k_average_return_delta" in validation["baseline_comparison"]


def test_bucket_only_models_reject_missing_bucket_features(tmp_path) -> None:
    db_path = tmp_path / "bucket-models-missing.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_model_table(conn, include_volume=False)
        with pytest.raises(ValueError, match="no feature columns"):
            harness.run_bucket_only_models(
                conn,
                buckets=("volume",),
                train_end="2026-01-04",
                validation_end="2026-01-06",
                test_end="2026-01-08",
                embargo=0,
            )
    finally:
        conn.close()


def test_bucket_only_models_record_bucket_with_no_complete_rows(tmp_path) -> None:
    db_path = tmp_path / "bucket-models-null-volume.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_model_table(conn, all_null_volume=True)
        summary = harness.run_bucket_only_models(
            conn,
            buckets=("price", "volume"),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    assert summary["buckets"]["price_behavior"]["status"] == "computed"
    skipped = summary["buckets"]["volume_liquidity"]
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "train split has no complete rows"
    assert skipped["complete_split_ranges"]["train"]["rows"] == 0


def test_bucket_model_harness_cli_prints_report(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "bucket-models-cli.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_model_table(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        harness.sys,
        "argv",
        [
            "bucket_model_harness.py",
            "--db",
            str(db_path),
            "--buckets",
            "price",
            "--train-end",
            "2026-01-04",
            "--validation-end",
            "2026-01-06",
            "--test-end",
            "2026-01-08",
            "--embargo",
            "0",
            "--top-k",
            "1",
        ],
    )

    assert harness.main() == 0
    output = capsys.readouterr().out
    assert "Bucket-only factor model report" in output
    assert '"price_behavior"' in output
