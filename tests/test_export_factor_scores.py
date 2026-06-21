from __future__ import annotations

from datetime import date, timedelta

import duckdb

from scripts.experiments import export_factor_scores as export_scores


def seed_factor_score_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE factor_panel_v1 (
            ticker VARCHAR,
            date DATE,
            panel_name VARCHAR,
            px_signal DOUBLE,
            regime_signal DOUBLE,
            future_21d_return DOUBLE,
            winner_21d BIGINT,
            prior_21d_return DOUBLE,
            sector VARCHAR,
            industry VARCHAR,
            risk_beta_spy_21d DOUBLE,
            liq_adv_20d DOUBLE
        )
        """
    )
    start = date(2026, 1, 1)
    specs = [
        ("AAPL", 1.0, 0.5, "Technology", "Consumer Electronics", 1.2, 1000.0),
        ("MSFT", 0.3, 0.2, "Technology", "Software", 1.1, 2000.0),
        ("JPM", -0.8, -0.1, "Financials", "Banks", 0.8, 3000.0),
    ]
    rows = []
    for offset in range(8):
        trading_date = start + timedelta(days=offset)
        for ticker, px_signal, regime_signal, sector, industry, beta, liquidity in specs:
            future_return = px_signal * 0.02 + regime_signal * 0.01
            rows.append(
                (
                    ticker,
                    trading_date,
                    "unit",
                    px_signal,
                    regime_signal,
                    future_return,
                    int(future_return > 0),
                    px_signal * 0.005,
                    sector,
                    industry,
                    beta,
                    liquidity,
                )
            )
    conn.executemany(
        "INSERT INTO factor_panel_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def test_export_factor_scores_writes_unique_scored_table(tmp_path) -> None:
    db_path = tmp_path / "factor-scores.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_score_table(conn)
        summary = export_scores.export_factor_scores(
            conn,
            table_name="factor_panel_v1",
            output_table="scores_v1",
            bucket_stack=("price", "regime"),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            score_splits=("test",),
            embargo=0,
        )
        scored = conn.execute("SELECT * FROM scores_v1 ORDER BY date, ticker").fetchdf()
    finally:
        conn.close()

    assert summary["output_table"] == "scores_v1"
    assert summary["bucket_stack"] == ["price_behavior", "regime_context"]
    assert summary["train_complete_rows"] == 12
    assert summary["scored_rows"] == 6
    assert summary["scored_split_counts"] == {"test": 6}
    assert summary["duplicate_key_count"] == 0
    assert summary["optional_columns"] == [
        "sector",
        "industry",
        "risk_beta_spy_21d",
        "liq_adv_20d",
    ]
    assert len(scored) == 6
    assert scored.duplicated(["ticker", "date"]).sum() == 0
    assert scored["prediction_score"].notna().all()
    assert set(scored["split"]) == {"test"}
    assert {
        "ticker",
        "date",
        "prediction_score",
        "future_21d_return",
        "sector",
        "industry",
        "risk_beta_spy_21d",
        "liq_adv_20d",
    }.issubset(scored.columns)


def test_parse_score_splits_rejects_unknown_split() -> None:
    try:
        export_scores.parse_score_splits(["validation", "holdout"])
    except ValueError as exc:
        assert "unsupported score split: holdout" == str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_export_factor_scores_cli_prints_report(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "factor-scores-cli.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_factor_score_table(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        export_scores.sys,
        "argv",
        [
            "export_factor_scores.py",
            "--db",
            str(db_path),
            "--table",
            "factor_panel_v1",
            "--output-table",
            "scores_v1",
            "--bucket-stack",
            "price",
            "regime",
            "--train-end",
            "2026-01-04",
            "--validation-end",
            "2026-01-06",
            "--test-end",
            "2026-01-08",
            "--score-splits",
            "test",
            "--embargo",
            "0",
        ],
    )

    assert export_scores.main() == 0
    output = capsys.readouterr().out
    assert "Factor score export report" in output
    assert '"output_table": "scores_v1"' in output
