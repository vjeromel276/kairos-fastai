from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from scripts.experiments import turnover_capacity_metrics as turnover


def scored_frame(rows: list[tuple[object, ...]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "date",
            "prediction_score",
            "future_21d_return",
            "liq_adv_20d",
        ],
    )


def test_turnover_metrics_detect_complete_turnover_and_cost_adjustment() -> None:
    df = scored_frame(
        [
            ("A", date(2026, 1, 1), 0.9, 0.01, 1000.0),
            ("B", date(2026, 1, 1), 0.8, 0.02, 2000.0),
            ("C", date(2026, 1, 1), 0.1, -0.01, 3000.0),
            ("D", date(2026, 1, 1), 0.0, -0.02, 4000.0),
            ("A", date(2026, 1, 2), 0.1, 0.01, 1000.0),
            ("B", date(2026, 1, 2), 0.0, 0.02, 2000.0),
            ("C", date(2026, 1, 2), 0.9, 0.03, 3000.0),
            ("D", date(2026, 1, 2), 0.8, 0.05, 4000.0),
        ]
    )

    report = turnover.run_turnover_capacity_metrics(df, top_k=2, cost_bps=10.0)

    second_day = report["turnover_by_date"][1]
    assert second_day["turnover"] == pytest.approx(1.0)
    assert second_day["holding_overlap"] == pytest.approx(0.0)
    assert second_day["gross_return"] == pytest.approx(0.04)
    assert second_day["transaction_cost"] == pytest.approx(0.001)
    assert second_day["cost_adjusted_return"] == pytest.approx(0.039)
    assert report["average_turnover"] == pytest.approx(1.0)
    assert report["liquidity_summary"]["average_liquidity"] == pytest.approx(2500.0)


def test_turnover_metrics_detect_no_turnover() -> None:
    df = scored_frame(
        [
            ("A", date(2026, 1, 1), 0.9, 0.01, 1000.0),
            ("B", date(2026, 1, 1), 0.8, 0.02, 2000.0),
            ("C", date(2026, 1, 1), 0.1, -0.01, 3000.0),
            ("A", date(2026, 1, 2), 0.9, 0.03, 1000.0),
            ("B", date(2026, 1, 2), 0.8, 0.04, 2000.0),
            ("C", date(2026, 1, 2), 0.1, -0.02, 3000.0),
        ]
    )

    report = turnover.run_turnover_capacity_metrics(df, top_k=2)

    assert report["turnover_by_date"][1]["turnover"] == pytest.approx(0.0)
    assert report["turnover_by_date"][1]["holding_overlap"] == pytest.approx(1.0)
    assert report["average_turnover"] == pytest.approx(0.0)
    assert report["average_holding_overlap"] == pytest.approx(1.0)


def test_turnover_metrics_skip_missing_score_days() -> None:
    df = scored_frame(
        [
            ("A", date(2026, 1, 1), 0.9, 0.01, 1000.0),
            ("B", date(2026, 1, 1), 0.8, 0.02, 2000.0),
            ("A", date(2026, 1, 2), None, 0.03, 1000.0),
            ("B", date(2026, 1, 2), None, 0.04, 2000.0),
            ("A", date(2026, 1, 3), 0.9, 0.05, 1000.0),
            ("B", date(2026, 1, 3), 0.8, 0.06, 2000.0),
        ]
    )

    report = turnover.run_turnover_capacity_metrics(df, top_k=2)

    assert report["selected_date_count"] == 2
    assert report["missing_score_date_count"] == 1
    assert [row["date"] for row in report["turnover_by_date"]] == [
        date(2026, 1, 1),
        date(2026, 1, 3),
    ]


def test_turnover_capacity_cli_runs_on_temp_duckdb_fixture(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    db_path = tmp_path / "turnover.duckdb"
    frame = scored_frame(
        [
            ("A", date(2026, 1, 1), 0.9, 0.01, 1000.0),
            ("B", date(2026, 1, 1), 0.8, 0.02, 2000.0),
            ("A", date(2026, 1, 2), 0.9, 0.03, 1000.0),
            ("B", date(2026, 1, 2), 0.8, 0.04, 2000.0),
        ]
    )
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE scored_panel AS
            SELECT * FROM frame
            """
        )
    finally:
        conn.close()

    monkeypatch.setattr(
        turnover.sys,
        "argv",
        [
            "turnover_capacity_metrics.py",
            "--db",
            str(db_path),
            "--table",
            "scored_panel",
            "--top-k",
            "2",
            "--cost-bps",
            "5",
        ],
    )

    assert turnover.main() == 0
    output = capsys.readouterr().out
    assert "Turnover and capacity metrics report" in output
    assert '"cost_adjusted_top_k_average_return"' in output
