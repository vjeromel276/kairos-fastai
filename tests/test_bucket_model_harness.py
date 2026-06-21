from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from scripts.experiments import bucket_model_harness as harness


def seed_factor_model_table(
    conn: duckdb.DuckDBPyConnection,
    include_volume: bool = True,
    all_null_volume: bool = False,
    include_turnover: bool = False,
    all_null_turnover: bool = True,
) -> None:
    volume_column = ", liq_signal DOUBLE" if include_volume else ""
    turnover_column = ", liq_turnover DOUBLE" if include_turnover else ""
    conn.execute(
        f"""
        CREATE TABLE factor_panel_v1 (
            ticker VARCHAR,
            date DATE,
            panel_name VARCHAR,
            px_signal DOUBLE
            {volume_column}
            {turnover_column},
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
                row = [
                    ticker,
                    trading_date,
                    "unit",
                    signal,
                    None if all_null_volume else signal * 10.0,
                ]
                if include_turnover:
                    row.append(None if all_null_turnover else signal * 0.01)
                row.extend(
                    [
                        future_return,
                        int(future_return > 0),
                        prior_return,
                    ]
                )
                rows.append(tuple(row))
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
    column_count = 7
    if include_volume:
        column_count += 1
    if include_turnover:
        column_count += 1
    placeholders = ", ".join(["?"] * column_count)
    conn.executemany(f"INSERT INTO factor_panel_v1 VALUES ({placeholders})", rows)


def seed_valuation_model_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE factor_panel_v1 (
            ticker VARCHAR,
            date DATE,
            panel_name VARCHAR,
            val_earnings_yield DOUBLE,
            val_fcf_yield DOUBLE,
            future_21d_return DOUBLE,
            winner_21d BIGINT,
            prior_21d_return DOUBLE
        )
        """
    )
    start = date(2026, 1, 1)
    specs = [
        ("AAPL", 0.10, 0.03, 0.01),
        ("MSFT", 0.05, 0.01, 0.00),
        ("JPM", -0.02, -0.02, -0.01),
    ]
    rows = []
    for offset in range(8):
        trading_date = start + timedelta(days=offset)
        for ticker, value_signal, future_return, prior_return in specs:
            rows.append(
                (
                    ticker,
                    trading_date,
                    "unit",
                    value_signal,
                    None,
                    future_return,
                    int(future_return > 0),
                    prior_return,
                )
            )
    conn.executemany("INSERT INTO factor_panel_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


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


def test_bucket_only_models_skip_sparse_optional_feature_without_skipping_bucket(
    tmp_path,
) -> None:
    db_path = tmp_path / "bucket-models-optional-turnover.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_model_table(conn, include_turnover=True, all_null_turnover=True)
        summary = harness.run_bucket_only_models(
            conn,
            buckets=("volume",),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    volume = summary["buckets"]["volume_liquidity"]
    assert volume["status"] == "computed"
    assert volume["feature_columns"] == ["liq_signal"]
    policy = volume["feature_policy"]
    assert policy["required_columns"] == ["liq_signal"]
    assert policy["optional_columns"] == ["liq_turnover"]
    assert policy["used_optional_columns"] == []
    assert policy["skipped_optional_columns"][0]["column"] == "liq_turnover"
    assert (
        policy["skipped_optional_columns"][0]["reason"]
        == "optional feature has missing values in required-complete rows"
    )


def test_bucket_only_models_skip_sparse_optional_valuation_feature(tmp_path) -> None:
    db_path = tmp_path / "bucket-models-optional-valuation.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_valuation_model_table(conn)
        summary = harness.run_bucket_only_models(
            conn,
            buckets=("valuation",),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    valuation = summary["buckets"]["valuation"]
    assert valuation["status"] == "computed"
    assert valuation["feature_columns"] == ["val_earnings_yield"]
    policy = valuation["feature_policy"]
    assert policy["required_columns"] == ["val_earnings_yield"]
    assert policy["optional_columns"] == ["val_fcf_yield"]
    assert policy["used_optional_columns"] == []
    assert policy["skipped_optional_columns"][0]["column"] == "val_fcf_yield"


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
