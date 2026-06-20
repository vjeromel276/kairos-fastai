from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.experiments.price_behavior_features import (
    add_price_behavior_features,
    add_price_behavior_features_for_panel,
)


def price_frame(days: int = 30) -> pd.DataFrame:
    start = date(2026, 1, 1)
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=offset) for offset in range(days)],
            "close": [1000.0 + offset for offset in range(days)],
            "closeadj": [100.0 + offset for offset in range(days)],
        }
    )


def test_price_returns_use_adjusted_prices_and_do_not_mutate_input() -> None:
    prices = price_frame()
    original = prices.copy(deep=True)

    result = add_price_behavior_features(
        prices,
        return_periods=(1, 5),
        ma_windows=(),
        drawdown_windows=(),
    )

    pd.testing.assert_frame_equal(prices, original)
    assert result["px_return_1d"].iloc[0] != 1001.0 / 1000.0 - 1.0
    assert result["px_return_1d"].iloc[1] == pytest.approx(101.0 / 100.0 - 1.0)
    assert result["px_return_5d"].iloc[5] == pytest.approx(105.0 / 100.0 - 1.0)


def test_price_behavior_warmup_nulls_are_deterministic() -> None:
    result = add_price_behavior_features(
        price_frame(days=30),
        return_periods=(21,),
        ma_windows=(21,),
        drawdown_windows=(21,),
        short_reversal_period=5,
    )

    assert result["px_return_21d"].iloc[:21].isna().all()
    assert result["px_return_21d"].iloc[21] == pytest.approx(121.0 / 100.0 - 1.0)
    assert result["px_ma_dist_21d"].iloc[:20].isna().all()
    assert result["px_ma_dist_21d"].iloc[20] == pytest.approx(120.0 / 110.0 - 1.0)
    assert result["px_drawdown_21d"].iloc[:20].isna().all()
    assert result["px_drawdown_21d"].iloc[20] == pytest.approx(0.0)


def test_price_behavior_drawdown_from_rolling_high() -> None:
    prices = pd.DataFrame(
        {
            "date": [date(2026, 1, 1) + timedelta(days=offset) for offset in range(6)],
            "closeadj": [100.0, 110.0, 105.0, 90.0, 95.0, 80.0],
        }
    )

    result = add_price_behavior_features(
        prices,
        return_periods=(1,),
        ma_windows=(),
        drawdown_windows=(3,),
        short_reversal_period=1,
    )

    assert result["px_drawdown_3d"].iloc[:2].isna().all()
    assert result["px_drawdown_3d"].iloc[2] == pytest.approx(105.0 / 110.0 - 1.0)
    assert result["px_drawdown_3d"].iloc[3] == pytest.approx(90.0 / 110.0 - 1.0)
    assert result["px_drawdown_3d"].iloc[5] == pytest.approx(80.0 / 95.0 - 1.0)


def test_short_reversal_is_negative_recent_return() -> None:
    result = add_price_behavior_features(
        price_frame(days=10),
        return_periods=(5,),
        ma_windows=(),
        drawdown_windows=(),
        short_reversal_period=5,
    )

    assert result["px_short_reversal_5d"].iloc[:5].isna().all()
    assert result["px_short_reversal_5d"].iloc[5] == pytest.approx(
        -result["px_return_5d"].iloc[5]
    )


def test_panel_price_features_do_not_cross_ticker_boundaries() -> None:
    start = date(2026, 1, 1)
    rows = []
    for offset in range(4):
        rows.append(("AAPL", start + timedelta(days=offset), 100.0 + offset))
        rows.append(("MSFT", start + timedelta(days=offset), 200.0 - offset))
    panel = pd.DataFrame(rows, columns=["ticker", "date", "closeadj"])

    result = add_price_behavior_features_for_panel(
        panel,
        return_periods=(1,),
        ma_windows=(),
        drawdown_windows=(),
        short_reversal_period=1,
    )

    aapl = result[result["ticker"] == "AAPL"].reset_index(drop=True)
    msft = result[result["ticker"] == "MSFT"].reset_index(drop=True)
    assert aapl["px_return_1d"].iloc[0] is pd.NA or pd.isna(aapl["px_return_1d"].iloc[0])
    assert msft["px_return_1d"].iloc[0] is pd.NA or pd.isna(msft["px_return_1d"].iloc[0])
    assert aapl["px_return_1d"].iloc[1] == pytest.approx(101.0 / 100.0 - 1.0)
    assert msft["px_return_1d"].iloc[1] == pytest.approx(199.0 / 200.0 - 1.0)


def test_price_behavior_rejects_invalid_periods() -> None:
    with pytest.raises(ValueError, match="return_periods"):
        add_price_behavior_features(price_frame(), return_periods=(1, 0))
