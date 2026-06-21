from __future__ import annotations

from datetime import date

import duckdb
import pytest

from scripts.experiments import factor_neutrality_diagnostics as neutrality


def scored_rows(include_sector: bool = True) -> list[tuple[object, ...]]:
    base_rows = [
        ("AAPL", date(2026, 1, 1), "Technology", 0.90, 0.04, 1.4),
        ("MSFT", date(2026, 1, 1), "Technology", 0.80, 0.03, 1.2),
        ("JPM", date(2026, 1, 1), "Financials", 0.20, 0.01, 0.8),
        ("BAC", date(2026, 1, 1), "Financials", 0.10, -0.01, 0.7),
        ("AAPL", date(2026, 1, 2), "Technology", 0.90, 0.05, 1.5),
        ("MSFT", date(2026, 1, 2), "Technology", 0.80, 0.02, 1.2),
        ("JPM", date(2026, 1, 2), "Financials", 0.20, 0.01, 0.8),
        ("BAC", date(2026, 1, 2), "Financials", 0.10, -0.02, 0.7),
    ]
    if include_sector:
        return base_rows
    return [(ticker, dt, score, target, beta) for ticker, dt, _, score, target, beta in base_rows]


def test_neutrality_diagnostics_report_sector_concentration_and_breakdown() -> None:
    import pandas as pd

    df = pd.DataFrame(
        scored_rows(),
        columns=[
            "ticker",
            "date",
            "sector",
            "prediction_score",
            "future_21d_return",
            "risk_beta_spy_21d",
        ],
    )

    report = neutrality.run_factor_neutrality_diagnostics(
        df,
        beta_column="risk_beta_spy_21d",
        top_k=1,
    )

    assert report["full_panel"]["top_k_average_return"] == pytest.approx(0.045)
    assert report["sector"]["status"] == "computed"
    assert report["sector"]["sector_neutral"]["sector_count"] == 2
    assert report["sector"]["sector_neutral"]["top_k_average_return"] == pytest.approx(
        (0.04 + 0.01 + 0.05 + 0.01) / 4
    )
    assert report["sector"]["top_k_concentration"]["sector_pick_shares"] == {
        "Technology": 1.0
    }
    assert set(report["sector"]["sector_breakdown"]) == {"Technology", "Financials"}


def test_neutrality_diagnostics_skip_sector_when_column_missing() -> None:
    import pandas as pd

    df = pd.DataFrame(
        scored_rows(include_sector=False),
        columns=[
            "ticker",
            "date",
            "prediction_score",
            "future_21d_return",
            "risk_beta_spy_21d",
        ],
    )

    report = neutrality.run_factor_neutrality_diagnostics(
        df,
        beta_column="risk_beta_spy_21d",
        top_k=1,
    )

    assert report["sector"]["status"] == "skipped"
    assert "sector column missing" in report["sector"]["reason"]


def test_beta_adjusted_diagnostics_are_computed_when_beta_is_available() -> None:
    import pandas as pd

    df = pd.DataFrame(
        scored_rows(),
        columns=[
            "ticker",
            "date",
            "sector",
            "prediction_score",
            "future_21d_return",
            "risk_beta_spy_21d",
        ],
    )

    report = neutrality.run_factor_neutrality_diagnostics(
        df,
        beta_column="risk_beta_spy_21d",
        top_k=1,
    )

    assert report["beta_adjusted"]["status"] == "computed"
    assert report["beta_adjusted"]["beta_column"] == "risk_beta_spy_21d"
    assert report["beta_adjusted"]["ranking"]["date_count"] == 2


def test_neutrality_diagnostics_include_split_summary_when_available() -> None:
    import pandas as pd

    df = pd.DataFrame(
        scored_rows(),
        columns=[
            "ticker",
            "date",
            "sector",
            "prediction_score",
            "future_21d_return",
            "risk_beta_spy_21d",
        ],
    )
    df["split"] = df["date"].map(
        {
            date(2026, 1, 1): "validation",
            date(2026, 1, 2): "test",
        }
    )

    report = neutrality.run_factor_neutrality_diagnostics(
        df,
        beta_column="risk_beta_spy_21d",
        top_k=1,
    )

    split_summary = report["split_summary"]
    assert split_summary["status"] == "computed"
    assert set(split_summary["splits"]) == {"validation", "test"}
    assert report["full_panel"]["top_k_average_return"] == pytest.approx(0.045)
    assert split_summary["splits"]["validation"]["row_count"] == 4
    assert split_summary["splits"]["validation"]["full_panel"][
        "top_k_average_return"
    ] == pytest.approx(0.04)
    assert split_summary["splits"]["test"]["row_count"] == 4
    assert split_summary["splits"]["test"]["full_panel"][
        "top_k_average_return"
    ] == pytest.approx(0.05)


def test_neutrality_cli_runs_on_temp_duckdb_fixture(monkeypatch, tmp_path, capsys) -> None:
    db_path = tmp_path / "neutrality.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE scored_panel (
                ticker VARCHAR,
                date DATE,
                sector VARCHAR,
                prediction_score DOUBLE,
                future_21d_return DOUBLE,
                risk_beta_spy_21d DOUBLE
            )
            """
        )
        conn.executemany("INSERT INTO scored_panel VALUES (?, ?, ?, ?, ?, ?)", scored_rows())
    finally:
        conn.close()

    monkeypatch.setattr(
        neutrality.sys,
        "argv",
        [
            "factor_neutrality_diagnostics.py",
            "--db",
            str(db_path),
            "--table",
            "scored_panel",
            "--beta-column",
            "risk_beta_spy_21d",
            "--top-k",
            "1",
        ],
    )

    assert neutrality.main() == 0
    output = capsys.readouterr().out
    assert "Factor neutrality diagnostics report" in output
    assert '"sector"' in output
