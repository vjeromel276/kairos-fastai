from __future__ import annotations

from datetime import date, timedelta

import duckdb

from scripts.experiments import bucket_ablation_harness as ablations


def seed_ablation_table(
    conn: duckdb.DuckDBPyConnection,
    all_null_volume: bool = False,
) -> None:
    conn.execute(
        """
        CREATE TABLE factor_panel_v1 (
            ticker VARCHAR,
            date DATE,
            panel_name VARCHAR,
            px_signal DOUBLE,
            liq_signal DOUBLE,
            future_21d_return DOUBLE,
            winner_21d BIGINT,
            prior_21d_return DOUBLE
        )
        """
    )
    start = date(2026, 1, 1)
    specs = [
        ("AAPL", 1.0, 10.0, 0.03, 0.01),
        ("MSFT", 0.8, 8.0, 0.02, 0.00),
        ("JPM", -1.0, -10.0, -0.01, -0.01),
    ]
    rows = []
    for offset in range(8):
        trading_date = start + timedelta(days=offset)
        for ticker, px_signal, liq_signal, future_return, prior_return in specs:
            rows.append(
                (
                    ticker,
                    trading_date,
                    "unit",
                    px_signal,
                    None
                    if all_null_volume or trading_date == date(2026, 1, 5)
                    else liq_signal,
                    future_return,
                    int(future_return > 0),
                    prior_return,
                )
            )
    conn.executemany("INSERT INTO factor_panel_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def test_cumulative_ablations_report_deltas_and_keep_decisions(tmp_path) -> None:
    db_path = tmp_path / "bucket-ablations.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_ablation_table(conn)
        summary = ablations.run_cumulative_bucket_ablations(
            conn,
            bucket_order=("price", "volume"),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    assert summary["mode"] == "cumulative_bucket_ablation"
    assert summary["bucket_order"] == ["price_behavior", "volume_liquidity"]
    assert len(summary["steps"]) == 2
    assert summary["steps"][0]["keep"] is True
    assert summary["steps"][0]["recommendation"] == "keep"
    assert summary["steps"][0]["deltas_vs_prior_accepted"][
        "validation_top_k_average_return_delta"
    ] is None

    second = summary["steps"][1]
    assert second["prior_accepted_stack"] == ["price_behavior"]
    assert second["candidate_stack"] == ["price_behavior", "volume_liquidity"]
    assert isinstance(second["keep"], bool)
    assert second["recommendation"] in {"keep", "watch", "reject"}
    assert "test_top_k_average_return_delta" in second["deltas_vs_prior_accepted"]
    assert "test_degradation_visible" in second["deltas_vs_prior_accepted"]


def test_ablation_comparisons_use_same_complete_rows_for_prior_and_candidate(
    tmp_path,
) -> None:
    db_path = tmp_path / "bucket-ablations-rows.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_ablation_table(conn)
        summary = ablations.run_cumulative_bucket_ablations(
            conn,
            bucket_order=("price", "volume"),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    second = summary["steps"][1]
    comparison_ranges = second["comparison_split_ranges"]
    assert second["prior_comparison"]["complete_split_ranges"] == comparison_ranges
    assert second["candidate"]["complete_split_ranges"] == comparison_ranges
    assert comparison_ranges["validation"]["rows"] == 3


def test_cumulative_ablations_record_sparse_candidate_as_reject(tmp_path) -> None:
    db_path = tmp_path / "bucket-ablations-sparse.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_ablation_table(conn, all_null_volume=True)
        summary = ablations.run_cumulative_bucket_ablations(
            conn,
            bucket_order=("price", "volume"),
            train_end="2026-01-04",
            validation_end="2026-01-06",
            test_end="2026-01-08",
            embargo=0,
            top_k=1,
        )
    finally:
        conn.close()

    second = summary["steps"][1]
    assert second["prior_accepted_stack"] == ["price_behavior"]
    assert second["accepted_stack_after"] == ["price_behavior"]
    assert second["keep"] is False
    assert second["recommendation"] == "reject"
    assert second["candidate"]["status"] == "skipped"
    assert second["candidate"]["reason"] == "train split has no complete rows"
    assert second["comparison_split_ranges"]["train"]["rows"] == 0
    assert second["prior_comparison"] is None


def test_candidate_recommendation_marks_test_degradation_watch() -> None:
    deltas = {
        "validation_top_k_average_return_delta": 0.01,
        "validation_mean_information_coefficient_delta": 0.02,
        "test_top_k_average_return_delta": -0.01,
        "test_mean_information_coefficient_delta": -0.02,
        "test_degradation_visible": True,
    }

    assert ablations.candidate_recommendation(deltas) == "watch"
    assert ablations.should_keep_candidate(deltas) is False


def test_bucket_ablation_cli_prints_report(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "bucket-ablations-cli.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        seed_ablation_table(conn)
    finally:
        conn.close()

    monkeypatch.setattr(
        ablations.sys,
        "argv",
        [
            "bucket_ablation_harness.py",
            "--db",
            str(db_path),
            "--bucket-order",
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

    assert ablations.main() == 0
    output = capsys.readouterr().out
    assert "Cumulative bucket ablation report" in output
    assert '"price_behavior"' in output
