from __future__ import annotations

from datetime import date, timedelta

import duckdb

from scripts.experiments import check_factor_dataset_quality as quality


def seed_factor_panel(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE factor_panel_v1 (
            ticker VARCHAR,
            date DATE,
            panel_name VARCHAR,
            future_21d_return DOUBLE,
            winner_21d BIGINT,
            future_5d_return DOUBLE,
            winner_5d BIGINT,
            px_return_21d DOUBLE,
            xs_px_return_21d_rank DOUBLE,
            liq_dollar_volume DOUBLE,
            risk_vol_21d DOUBLE,
            regime_spy_trend_200d DOUBLE
        )
        """
    )
    start = date(2026, 1, 1)
    rows = []
    for ticker_index, ticker in enumerate(["AAPL", "MSFT"]):
        for offset in range(30):
            trading_date = start + timedelta(days=offset)
            future_21d_return = None if offset >= 9 else 0.01 + ticker_index * 0.01
            winner_21d = None if future_21d_return is None else int(future_21d_return > 0)
            future_5d_return = None if offset >= 25 else 0.005 + ticker_index * 0.01
            winner_5d = None if future_5d_return is None else int(future_5d_return > 0)
            warmup_value = None if offset < 21 else 0.02
            rows.append(
                (
                    ticker,
                    trading_date,
                    "large_cap_fixed",
                    future_21d_return,
                    winner_21d,
                    future_5d_return,
                    winner_5d,
                    warmup_value,
                    0.25 + ticker_index * 0.5,
                    1_000_000.0 + offset,
                    warmup_value,
                    1.0,
                )
            )
    conn.executemany(
        """
        INSERT INTO factor_panel_v1
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def build_factor_fixture(db_path) -> None:
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_panel(conn)
    finally:
        conn.close()


def test_factor_quality_checker_reports_valid_panel(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "factor-quality-valid.duckdb"
    build_factor_fixture(db_path)

    monkeypatch.setattr(
        quality.sys,
        "argv",
        [
            "check_factor_dataset_quality.py",
            "--db",
            str(db_path),
        ],
    )

    assert quality.main() == 0
    output = capsys.readouterr().out

    assert "Factor dataset quality report: factor_panel_v1" in output
    assert "Rows: 60" in output
    assert "Tickers: 2" in output
    assert "Panels: 1" in output
    assert "Duplicate ticker/date keys: 0" in output
    assert "price_behavior: columns=1" in output
    assert "cross_sectional_context: columns=1" in output
    assert "volume_liquidity: columns=1" in output
    assert "volatility_risk: columns=1" in output
    assert "regime_context: columns=1" in output
    assert "horizon_21d:" in output
    assert "target_available_rows: 18" in output
    assert "horizon_5d:" in output
    assert "target_available_rows: 50" in output
    assert "Valid: True" in output


def test_factor_quality_checker_reports_optional_turnover_status(tmp_path) -> None:
    db_path = tmp_path / "factor-quality-turnover.duckdb"
    build_factor_fixture(db_path)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("ALTER TABLE factor_panel_v1 ADD COLUMN liq_turnover DOUBLE")
        report = quality.validate_factor_dataset_quality(conn)
    finally:
        conn.close()

    turnover = report["feature_policy_availability"]["volume_liquidity"][
        "optional_feature_status"
    ]["liq_turnover"]
    assert turnover["role"] == "optional"
    assert turnover["status"] == "skipped"
    assert turnover["non_null_rows"] == 0
    assert turnover["reason"] == "optional feature all null"


def test_factor_quality_checker_reports_optional_cash_flow_yield_status(tmp_path) -> None:
    db_path = tmp_path / "factor-quality-fcf-yield.duckdb"
    build_factor_fixture(db_path)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("ALTER TABLE factor_panel_v1 ADD COLUMN val_earnings_yield DOUBLE")
        conn.execute("ALTER TABLE factor_panel_v1 ADD COLUMN val_fcf_yield DOUBLE")
        conn.execute("UPDATE factor_panel_v1 SET val_earnings_yield = 0.05")
        report = quality.validate_factor_dataset_quality(conn)
    finally:
        conn.close()

    fcf_yield = report["feature_policy_availability"]["valuation"][
        "optional_feature_status"
    ]["val_fcf_yield"]
    assert fcf_yield["role"] == "optional"
    assert fcf_yield["status"] == "skipped"
    assert fcf_yield["non_null_rows"] == 0
    assert fcf_yield["reason"] == "optional feature all null"


def test_factor_quality_checker_reports_bucket_coverage_by_split(tmp_path) -> None:
    db_path = tmp_path / "factor-quality-splits.duckdb"
    build_factor_fixture(db_path)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("ALTER TABLE factor_panel_v1 ADD COLUMN qual_recent DOUBLE")
        conn.execute(
            """
            UPDATE factor_panel_v1
            SET qual_recent = 1.0
            WHERE date >= DATE '2026-01-21'
            """
        )
        report = quality.validate_factor_dataset_quality(
            conn,
            target_horizons=(5,),
            train_end="2026-01-10",
            validation_end="2026-01-20",
            test_end="2026-01-30",
            embargo=0,
        )
    finally:
        conn.close()

    fundamental = report["bucket_split_availability"]["fundamental_quality"]
    assert fundamental["train"]["rows_with_all_values"] == 0
    assert fundamental["validation"]["rows_with_all_values"] == 0
    assert fundamental["test"]["rows_with_all_values"] == 20
    assert fundamental["test"]["rows_with_all_values_and_primary_target"] == 10


def test_factor_quality_checker_fails_on_duplicate_ticker_date(tmp_path) -> None:
    db_path = tmp_path / "factor-quality-duplicates.duckdb"
    build_factor_fixture(db_path)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO factor_panel_v1
            SELECT *
            FROM factor_panel_v1
            WHERE ticker = 'AAPL'
              AND date = DATE '2026-01-03'
            """
        )
        report = quality.validate_factor_dataset_quality(conn)
    finally:
        conn.close()

    assert report["valid"] is False
    assert report["duplicate_key_count"] == 1


def test_factor_quality_checker_fails_on_target_winner_mismatch(tmp_path) -> None:
    db_path = tmp_path / "factor-quality-targets.duckdb"
    build_factor_fixture(db_path)

    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            UPDATE factor_panel_v1
            SET winner_21d = NULL
            WHERE ticker = 'AAPL'
              AND date = DATE '2026-01-02'
            """
        )
        conn.execute(
            """
            UPDATE factor_panel_v1
            SET winner_5d = 1
            WHERE ticker = 'MSFT'
              AND date = DATE '2026-01-30'
            """
        )
        report = quality.validate_factor_dataset_quality(conn)
    finally:
        conn.close()

    assert report["valid"] is False
    assert report["target_availability"]["21"]["unexpected_winner_nulls"] == 1
    assert report["target_availability"]["5"]["unexpected_winner_values"] == 1


def test_factor_quality_checker_reports_missing_required_columns(tmp_path) -> None:
    db_path = tmp_path / "factor-quality-missing.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE factor_panel_v1 (
                ticker VARCHAR,
                date DATE,
                panel_name VARCHAR,
                future_21d_return DOUBLE,
                winner_21d BIGINT
            )
            """
        )
        report = quality.validate_factor_dataset_quality(conn)
    finally:
        conn.close()

    assert report["valid"] is False
    assert report["missing_columns"] == ["future_5d_return", "winner_5d"]
