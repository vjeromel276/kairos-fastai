from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.experiments.cross_sectional_features import (
    add_cross_sectional_context_features,
    add_cross_sectional_rank_features,
    add_cross_sectional_zscore_features,
    add_market_relative_features,
    add_sector_relative_features,
)


def test_cross_sectional_ranks_are_fit_per_date_without_future_leakage() -> None:
    panel = pd.DataFrame(
        {
            "date": [
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 2),
            ],
            "ticker": ["AAPL", "MSFT", "AAPL", "MSFT"],
            "px_return_21d": [0.01, 0.03, 1.00, -1.00],
        }
    )
    changed_future = panel.copy()
    changed_future.loc[changed_future["date"] == date(2026, 1, 2), "px_return_21d"] = [
        -100.0,
        100.0,
    ]

    ranked = add_cross_sectional_rank_features(panel, ["px_return_21d"])
    ranked_changed = add_cross_sectional_rank_features(changed_future, ["px_return_21d"])

    date_one = ranked[ranked["date"] == date(2026, 1, 1)].reset_index(drop=True)
    changed_date_one = ranked_changed[
        ranked_changed["date"] == date(2026, 1, 1)
    ].reset_index(drop=True)
    pd.testing.assert_series_equal(
        date_one["xs_px_return_21d_rank"],
        changed_date_one["xs_px_return_21d_rank"],
        check_names=False,
    )
    assert date_one["xs_px_return_21d_rank"].tolist() == [0.5, 1.0]


def test_cross_sectional_zscores_are_calculated_per_date() -> None:
    panel = pd.DataFrame(
        {
            "date": [
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 2),
            ],
            "ticker": ["AAPL", "MSFT", "AAPL", "MSFT"],
            "liq_dollar_volume": [1.0, 3.0, 100.0, 100.0],
        }
    )

    result = add_cross_sectional_zscore_features(
        panel,
        ["liq_dollar_volume"],
        winsor_limits=(0.0, 1.0),
    )

    first_date = result[result["date"] == date(2026, 1, 1)]
    second_date = result[result["date"] == date(2026, 1, 2)]
    assert first_date["xs_liq_dollar_volume_z"].tolist() == pytest.approx([-1.0, 1.0])
    assert second_date["xs_liq_dollar_volume_z"].tolist() == pytest.approx([0.0, 0.0])


def test_market_relative_features_use_exact_spy_dates_without_forward_fill() -> None:
    panel = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "ticker": ["AAPL", "AAPL"],
            "px_return_21d": [0.05, 0.06],
        }
    )
    spy = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)],
            "px_return_21d": [0.02],
        }
    )

    result = add_market_relative_features(panel, spy, ["px_return_21d"])

    assert result["xs_px_return_21d_minus_spy"].iloc[0] == pytest.approx(0.03)
    assert pd.isna(result["xs_px_return_21d_minus_spy"].iloc[1])


def test_sector_relative_features_use_same_date_and_sector() -> None:
    panel = pd.DataFrame(
        {
            "date": [
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 1),
            ],
            "ticker": ["AAPL", "MSFT", "JPM"],
            "sector": ["Technology", "Technology", "Financial Services"],
            "px_return_21d": [0.03, 0.01, 0.04],
        }
    )

    result = add_sector_relative_features(panel, ["px_return_21d"])

    assert result["xs_px_return_21d_minus_sector"].iloc[0] == pytest.approx(0.01)
    assert result["xs_px_return_21d_minus_sector"].iloc[1] == pytest.approx(-0.01)
    assert result["xs_px_return_21d_minus_sector"].iloc[2] == pytest.approx(0.0)


def test_sector_relative_features_are_null_when_sector_is_missing() -> None:
    panel = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 1)],
            "ticker": ["AAPL", "MSFT"],
            "px_return_21d": [0.03, 0.01],
        }
    )

    result = add_sector_relative_features(panel, ["px_return_21d"])

    assert result["xs_px_return_21d_minus_sector"].isna().all()


def test_cross_sectional_context_combines_selected_feature_families() -> None:
    panel = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 1)],
            "ticker": ["AAPL", "MSFT"],
            "sector": ["Technology", "Technology"],
            "px_return_21d": [0.03, 0.01],
            "liq_dollar_volume": [3.0, 1.0],
        }
    )
    spy = pd.DataFrame({"date": [date(2026, 1, 1)], "px_return_21d": [0.02]})

    result = add_cross_sectional_context_features(
        panel,
        rank_columns=["px_return_21d", "liq_dollar_volume"],
        zscore_columns=["liq_dollar_volume"],
        market_relative_columns=["px_return_21d"],
        sector_relative_columns=["px_return_21d"],
        market_proxy=spy,
        winsor_limits=(0.0, 1.0),
    )

    expected_columns = {
        "xs_px_return_21d_rank",
        "xs_liq_dollar_volume_rank",
        "xs_liq_dollar_volume_z",
        "xs_px_return_21d_minus_spy",
        "xs_px_return_21d_minus_sector",
    }
    assert expected_columns.issubset(result.columns)


def test_market_relative_features_require_proxy_when_configured() -> None:
    panel = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)],
            "ticker": ["AAPL"],
            "px_return_21d": [0.03],
        }
    )

    with pytest.raises(ValueError, match="market_proxy is required"):
        add_cross_sectional_context_features(
            panel,
            rank_columns=["px_return_21d"],
            market_relative_columns=["px_return_21d"],
        )
