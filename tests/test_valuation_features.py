from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.experiments.valuation_features import add_valuation_features


def test_daily_valuation_ratios_join_on_exact_date_and_allow_negative_yields() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 2)]})
    daily = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "date": [date(2026, 1, 2)],
            "pe": [-10.0],
            "ps": [2.0],
            "pb": [4.0],
            "evebit": [5.0],
            "evebitda": [10.0],
            "marketcap": [1000.0],
        }
    )

    result = add_valuation_features(panel, daily)

    assert result["val_earnings_yield"].iloc[0] == pytest.approx(-0.10)
    assert result["val_sales_yield"].iloc[0] == pytest.approx(0.50)
    assert result["val_book_yield"].iloc[0] == pytest.approx(0.25)
    assert result["val_ebit_ev_yield"].iloc[0] == pytest.approx(0.20)
    assert result["val_ebitda_ev_yield"].iloc[0] == pytest.approx(0.10)
    assert pd.isna(result["val_fcf_yield"].iloc[0])


def test_daily_valuation_ratios_are_not_forward_filled() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 3)]})
    daily = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "date": [date(2026, 1, 2)],
            "pe": [10.0],
        }
    )

    result = add_valuation_features(panel, daily)

    assert result["val_earnings_yield"].isna().all()


def test_zero_denominators_produce_null_valuation_features() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 10)]})
    daily = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "date": [date(2026, 1, 10)],
            "pe": [0.0],
            "ps": [0.0],
            "pb": [0.0],
            "evebit": [0.0],
            "evebitda": [0.0],
            "marketcap": [0.0],
        }
    )
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "dimension": ["MRT"],
            "datekey": [date(2026, 1, 5)],
            "lastupdated": [date(2026, 1, 5)],
            "fcf": [100.0],
        }
    )

    result = add_valuation_features(panel, daily, fundamentals=fundamentals)

    assert result.filter(like="val_").isna().all(axis=None)


def test_cash_flow_yield_uses_fundamental_point_in_time_policy() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL"],
            "date": [date(2026, 1, 4), date(2026, 1, 5)],
        }
    )
    daily = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL"],
            "date": [date(2026, 1, 4), date(2026, 1, 5)],
            "marketcap": [1000.0, 1000.0],
        }
    )
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "dimension": ["MRT"],
            "datekey": [date(2026, 1, 3)],
            "lastupdated": [date(2026, 1, 5)],
            "fcf": [100.0],
        }
    )

    result = add_valuation_features(panel, daily, fundamentals=fundamentals)

    assert pd.isna(result["val_fcf_yield"].iloc[0])
    assert result["val_fcf_yield"].iloc[1] == pytest.approx(0.10)


def test_extreme_valuation_yields_are_capped() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL"],
            "date": [date(2026, 1, 2), date(2026, 1, 3)],
        }
    )
    daily = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL"],
            "date": [date(2026, 1, 2), date(2026, 1, 3)],
            "pe": [0.01, -0.01],
        }
    )

    result = add_valuation_features(panel, daily, cap_bounds=(-0.5, 0.5))

    assert result["val_earnings_yield"].tolist() == pytest.approx([0.5, -0.5])


def test_missing_cash_flow_column_keeps_cash_flow_yield_null() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 10)]})
    daily = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "date": [date(2026, 1, 10)],
            "marketcap": [1000.0],
        }
    )
    fundamentals = pd.DataFrame(
        {
            "ticker": ["AAPL"],
            "dimension": ["MRT"],
            "datekey": [date(2026, 1, 5)],
            "lastupdated": [date(2026, 1, 5)],
        }
    )

    result = add_valuation_features(panel, daily, fundamentals=fundamentals)

    assert pd.isna(result["val_fcf_yield"].iloc[0])


def test_valuation_features_do_not_cross_ticker_boundaries() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT"],
            "date": [date(2026, 1, 10), date(2026, 1, 10)],
        }
    )
    daily = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT"],
            "date": [date(2026, 1, 10), date(2026, 1, 10)],
            "pe": [10.0, 20.0],
        }
    )

    result = add_valuation_features(panel, daily)

    assert result.loc[result["ticker"] == "AAPL", "val_earnings_yield"].iloc[0] == 0.10
    assert result.loc[result["ticker"] == "MSFT", "val_earnings_yield"].iloc[0] == 0.05


def test_valuation_features_reject_invalid_cap_bounds() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 10)]})
    daily = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 10)]})

    with pytest.raises(ValueError, match="cap_bounds"):
        add_valuation_features(panel, daily, cap_bounds=(1.0, -1.0))
