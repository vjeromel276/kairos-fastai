from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.experiments.fundamental_quality_features import (
    QUALITY_FEATURE_COLUMNS,
    add_fundamental_quality_features,
)


def test_quality_features_wait_for_later_of_datekey_and_lastupdated() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL", "AAPL", "AAPL"],
            "date": [
                date(2026, 1, 3),
                date(2026, 1, 4),
                date(2026, 1, 5),
                date(2026, 1, 6),
            ],
        }
    )
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "dimension": ["MRT"],
            "datekey": [date(2026, 1, 3)],
            "lastupdated": [date(2026, 1, 5)],
            "grossmargin": [0.42],
        }
    )

    result = add_fundamental_quality_features(panel, fundamentals)

    assert result["qual_gross_margin"].iloc[:2].isna().all()
    assert result["qual_gross_margin"].iloc[2] == pytest.approx(0.42)
    assert result["qual_gross_margin"].iloc[3] == pytest.approx(0.42)


def test_quality_ratios_use_components_and_zero_denominators_become_null() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 2, 1)]})
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "dimension": ["MRT"],
            "datekey": [date(2026, 1, 15)],
            "lastupdated": [date(2026, 1, 15)],
            "revenue": [100.0],
            "gp": [40.0],
            "ebit": [15.0],
            "netinc": [10.0],
            "assets": [1000.0],
            "equity": [500.0],
            "debt": [200.0],
            "roic": [0.03],
        }
    )

    result = add_fundamental_quality_features(panel, fundamentals)

    assert result["qual_gross_margin"].iloc[0] == pytest.approx(0.40)
    assert result["qual_operating_margin"].iloc[0] == pytest.approx(0.15)
    assert result["qual_net_margin"].iloc[0] == pytest.approx(0.10)
    assert result["qual_roa"].iloc[0] == pytest.approx(0.01)
    assert result["qual_roe"].iloc[0] == pytest.approx(0.02)
    assert result["qual_roic"].iloc[0] == pytest.approx(0.03)
    assert result["qual_debt_to_assets"].iloc[0] == pytest.approx(0.20)

    zero_denominator = fundamentals.copy()
    zero_denominator["assets"] = 0.0
    zero_result = add_fundamental_quality_features(panel, zero_denominator)
    assert pd.isna(zero_result["qual_roa"].iloc[0])
    assert pd.isna(zero_result["qual_debt_to_assets"].iloc[0])


def test_growth_features_use_only_prior_fundamental_rows() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL", "AAPL"],
            "date": [date(2026, 1, 10), date(2026, 2, 10), date(2026, 3, 10)],
        }
    )
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL", "AAPL"],
            "dimension": ["MRT", "MRT", "MRT"],
            "reportperiod": [
                date(2025, 12, 31),
                date(2026, 1, 31),
                date(2026, 2, 28),
            ],
            "datekey": [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)],
            "lastupdated": [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)],
            "revenue": [100.0, 110.0, 121.0],
            "netinc": [10.0, 11.0, 12.1],
        }
    )

    result = add_fundamental_quality_features(
        panel,
        fundamentals,
        growth_periods=1,
    )

    assert pd.isna(result["qual_revenue_growth"].iloc[0])
    assert result["qual_revenue_growth"].iloc[1] == pytest.approx(0.10)
    assert result["qual_revenue_growth"].iloc[2] == pytest.approx(0.10)
    assert result["qual_earnings_growth"].iloc[2] == pytest.approx(0.10)


def test_dimension_filter_uses_selected_dimension() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 10)]})
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL"],
            "dimension": ["MRY", "MRT"],
            "datekey": [date(2026, 1, 5), date(2026, 1, 5)],
            "lastupdated": [date(2026, 1, 5), date(2026, 1, 5)],
            "grossmargin": [0.90, 0.40],
        }
    )

    result = add_fundamental_quality_features(panel, fundamentals)

    assert result["qual_gross_margin"].iloc[0] == pytest.approx(0.40)


def test_fallback_lag_applies_when_datekey_is_missing() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL"],
            "date": [date(2026, 1, 10), date(2026, 1, 11)],
        }
    )
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "dimension": ["MRT"],
            "reportperiod": [date(2026, 1, 1)],
            "grossmargin": [0.35],
        }
    )

    result = add_fundamental_quality_features(
        panel,
        fundamentals,
        fallback_lag_days=10,
    )

    assert pd.isna(result["qual_gross_margin"].iloc[0])
    assert result["qual_gross_margin"].iloc[1] == pytest.approx(0.35)


def test_quality_features_do_not_cross_ticker_boundaries() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT"],
            "date": [date(2026, 1, 10), date(2026, 1, 10)],
        }
    )
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT"],
            "dimension": ["MRT", "MRT"],
            "datekey": [date(2026, 1, 5), date(2026, 1, 5)],
            "lastupdated": [date(2026, 1, 5), date(2026, 1, 5)],
            "grossmargin": [0.40, 0.20],
        }
    )

    result = add_fundamental_quality_features(panel, fundamentals)

    assert result.loc[result["ticker"] == "AAPL", "qual_gross_margin"].iloc[0] == 0.40
    assert result.loc[result["ticker"] == "MSFT", "qual_gross_margin"].iloc[0] == 0.20


def test_missing_source_columns_degrade_to_null_quality_features() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 10)]})
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "dimension": ["MRT"],
            "datekey": [date(2026, 1, 5)],
            "lastupdated": [date(2026, 1, 5)],
        }
    )

    result = add_fundamental_quality_features(panel, fundamentals)

    assert result[list(QUALITY_FEATURE_COLUMNS)].isna().all(axis=None)


def test_quality_features_reject_invalid_lag_and_growth_periods() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 10)]})
    fundamentals = pd.DataFrame({"ticker": ["AAPL"], "datekey": [date(2026, 1, 5)]})

    with pytest.raises(ValueError, match="fallback_lag_days"):
        add_fundamental_quality_features(
            panel,
            fundamentals.drop(columns=["datekey"]).assign(reportperiod=date(2026, 1, 1)),
            fallback_lag_days=-1,
        )

    with pytest.raises(ValueError, match="growth_periods"):
        add_fundamental_quality_features(panel, fundamentals, growth_periods=0)
