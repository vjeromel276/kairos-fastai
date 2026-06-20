from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd

from scripts.experiments import feature_redundancy_diagnostics as diagnostics


def redundancy_frame() -> pd.DataFrame:
    start = date(2026, 1, 1)
    return pd.DataFrame(
        {
            "ticker": ["AAPL"] * 5,
            "date": [start + timedelta(days=offset) for offset in range(5)],
            "panel_name": ["unit"] * 5,
            "future_21d_return": [0.01, 0.02, 0.03, 0.04, 0.05],
            "winner_21d": [1, 1, 1, 1, 1],
            "future_5d_return": [0.01, 0.02, 0.03, 0.04, 0.05],
            "winner_5d": [1, 1, 1, 1, 1],
            "px_return_21d": [1.0, 2.0, 3.0, 4.0, 5.0],
            "px_return_63d": [1.0, 2.0, 3.0, 4.0, 5.0],
            "liq_dollar_volume": [10.0, 10.0, 10.0, 10.0, 10.0],
            "risk_realized_vol_21d": [None, None, 3.0, None, 5.0],
            "val_earnings_yield": [None, None, 3.0, None, 5.0],
        }
    )


def test_redundancy_diagnostics_flag_duplicate_and_near_constant_features() -> None:
    report = diagnostics.run_feature_redundancy_diagnostics(
        redundancy_frame(),
        high_correlation_threshold=0.99,
        missingness_overlap_threshold=0.50,
    )

    high_pairs = {
        (item["feature_a"], item["feature_b"])
        for item in report["high_correlation_pairs"]
    }
    near_constant = {item["feature"]: item["reason"] for item in report["near_constant_features"]}

    assert ("px_return_21d", "px_return_63d") in high_pairs
    assert near_constant["liq_dollar_volume"] == "single_value"
    assert report["feature_count"] == 5
    assert any(
        item["feature_a"] == "risk_realized_vol_21d"
        and item["feature_b"] == "val_earnings_yield"
        for item in report["missingness_overlap_pairs"]
    )


def test_bucket_correlation_summary_is_reviewable() -> None:
    report = diagnostics.run_feature_redundancy_diagnostics(redundancy_frame())

    price_summary = [
        item
        for item in report["bucket_correlation_summary"]
        if item["bucket_a"] == "price_behavior" and item["bucket_b"] == "price_behavior"
    ]

    assert len(price_summary) == 1
    assert price_summary[0]["pair_count"] == 1
    assert price_summary[0]["max_abs_correlation"] == 1.0


def test_redundancy_diagnostics_can_run_on_temp_duckdb_fixture(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    db_path = tmp_path / "feature-redundancy.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        frame = redundancy_frame()
        conn.execute(
            """
            CREATE TABLE factor_panel_v1 AS
            SELECT * FROM frame
            """
        )
        report = diagnostics.validate_feature_redundancy(
            conn,
            table_name="factor_panel_v1",
            high_correlation_threshold=0.99,
        )
    finally:
        conn.close()

    assert report["table"] == "factor_panel_v1"
    assert report["row_count"] == 5

    monkeypatch.setattr(
        diagnostics.sys,
        "argv",
        [
            "feature_redundancy_diagnostics.py",
            "--db",
            str(db_path),
            "--table",
            "factor_panel_v1",
            "--high-correlation-threshold",
            "0.99",
        ],
    )

    assert diagnostics.main() == 0
    output = capsys.readouterr().out
    assert "Feature redundancy report: factor_panel_v1" in output
    assert "High-correlation pairs:" in output


def test_redundancy_diagnostics_validate_thresholds() -> None:
    frame = redundancy_frame()

    try:
        diagnostics.run_feature_redundancy_diagnostics(
            frame,
            high_correlation_threshold=1.1,
        )
    except ValueError as exc:
        assert "correlation threshold" in str(exc)
    else:
        raise AssertionError("expected invalid correlation threshold to fail")
