from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.experiments.regime_features import (
    add_regime_context_features,
    build_breadth_features,
    build_spy_regime_features,
)


def spy_frame(close_values: list[float]) -> pd.DataFrame:
    start = date(2026, 1, 1)
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=offset) for offset in range(len(close_values))],
            "closeadj": close_values,
        }
    )


def test_spy_regime_features_use_trailing_data_through_current_date() -> None:
    spy = spy_frame([100.0, 110.0, 105.0, 120.0])

    result = build_spy_regime_features(
        spy,
        trend_windows=(2,),
        vol_windows=(2,),
        drawdown_window=3,
        return_window=2,
    )

    assert result["regime_spy_return_2d"].iloc[2] == pytest.approx(105.0 / 100.0 - 1.0)
    assert result["regime_spy_trend_2d"].iloc[2] == pytest.approx(105.0 / 107.5 - 1.0)
    assert result["regime_spy_above_ma_2d"].iloc[2] == pytest.approx(0.0)
    assert result["regime_spy_drawdown_3d"].iloc[2] == pytest.approx(105.0 / 110.0 - 1.0)
    assert result["regime_spy_realized_vol_2d"].notna().iloc[2]
    assert result["regime_spy_risk_on_score_2d"].notna().iloc[2]


def test_regime_features_join_to_all_tickers_on_same_date() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT"],
            "date": [date(2026, 1, 3), date(2026, 1, 3)],
        }
    )
    spy = spy_frame([100.0, 110.0, 105.0])

    result = add_regime_context_features(
        panel,
        spy,
        trend_windows=(2,),
        vol_windows=(2,),
        drawdown_window=2,
        return_window=1,
    )

    values = result["regime_spy_return_1d"].tolist()
    assert values == pytest.approx([105.0 / 110.0 - 1.0, 105.0 / 110.0 - 1.0])


def test_missing_spy_dates_are_not_forward_filled() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 3)]})
    spy = spy_frame([100.0, 110.0])

    result = add_regime_context_features(
        panel,
        spy,
        trend_windows=(2,),
        vol_windows=(2,),
        drawdown_window=2,
        return_window=1,
    )

    assert result.filter(like="regime_spy_").isna().all(axis=None)


def test_regime_features_do_not_use_future_spy_prices() -> None:
    panel = pd.DataFrame({"ticker": ["AAPL"], "date": [date(2026, 1, 3)]})
    spy = spy_frame([100.0, 110.0, 105.0, 120.0])
    changed_future_spy = spy.copy()
    changed_future_spy.loc[3, "closeadj"] = 1000.0

    result = add_regime_context_features(
        panel,
        spy,
        trend_windows=(2,),
        vol_windows=(2,),
        drawdown_window=2,
        return_window=2,
    )
    changed_result = add_regime_context_features(
        panel,
        changed_future_spy,
        trend_windows=(2,),
        vol_windows=(2,),
        drawdown_window=2,
        return_window=2,
    )

    assert result["regime_spy_return_2d"].iloc[0] == pytest.approx(
        changed_result["regime_spy_return_2d"].iloc[0]
    )
    assert result["regime_spy_trend_2d"].iloc[0] == pytest.approx(
        changed_result["regime_spy_trend_2d"].iloc[0]
    )


def test_breadth_features_are_calculated_per_date_and_joined() -> None:
    panel = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT", "JPM"],
            "date": [date(2026, 1, 3), date(2026, 1, 3), date(2026, 1, 3)],
            "px_return_21d": [0.10, -0.05, None],
        }
    )
    spy = spy_frame([100.0, 110.0, 105.0])

    breadth = build_breadth_features(panel, ("px_return_21d",))
    result = add_regime_context_features(
        panel,
        spy,
        trend_windows=(2,),
        vol_windows=(2,),
        drawdown_window=2,
        return_window=1,
        breadth_columns=("px_return_21d",),
    )

    assert breadth["regime_breadth_px_return_21d_positive"].iloc[0] == pytest.approx(0.5)
    assert result["regime_breadth_px_return_21d_positive"].tolist() == pytest.approx(
        [0.5, 0.5, 0.5]
    )


def test_regime_features_reject_invalid_windows() -> None:
    spy = spy_frame([100.0, 101.0])

    with pytest.raises(ValueError, match="trend_windows"):
        build_spy_regime_features(spy, trend_windows=(2, 0))

    with pytest.raises(ValueError, match="drawdown_window"):
        build_spy_regime_features(spy, drawdown_window=0)
