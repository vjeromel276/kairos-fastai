from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.experiments.volume_liquidity_features import (
    add_volume_liquidity_features,
    add_volume_liquidity_features_for_panel,
)


def liquidity_frame(days: int = 25) -> pd.DataFrame:
    start = date(2026, 1, 1)
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=offset) for offset in range(days)],
            "closeadj": [10.0 + offset for offset in range(days)],
            "volume": [100.0 + offset * 10.0 for offset in range(days)],
        }
    )


def test_dollar_volume_and_rolling_liquidity_use_current_price_and_volume() -> None:
    prices = liquidity_frame()
    original = prices.copy(deep=True)

    result = add_volume_liquidity_features(prices, windows=(2, 20))

    pd.testing.assert_frame_equal(prices, original)
    assert result["liq_dollar_volume"].iloc[0] == pytest.approx(10.0 * 100.0)
    assert result["liq_volume_avg_2d"].iloc[0] is pd.NA or pd.isna(
        result["liq_volume_avg_2d"].iloc[0]
    )
    assert result["liq_volume_avg_2d"].iloc[1] == pytest.approx((100.0 + 110.0) / 2.0)
    expected_adv = ((10.0 * 100.0) + (11.0 * 110.0)) / 2.0
    assert result["liq_adv_2d"].iloc[1] == pytest.approx(expected_adv)
    assert result["liq_rel_volume_2d"].iloc[1] == pytest.approx(110.0 / 105.0)
    assert result["liq_adv_20d"].iloc[:19].isna().all()


def test_missing_price_or_volume_degrades_to_null_features_and_false_flags() -> None:
    prices = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "ticker": ["AAPL", "AAPL"],
        }
    )

    result = add_volume_liquidity_features(prices, windows=(2,))

    assert result["liq_dollar_volume"].isna().all()
    assert result["liq_volume_avg_2d"].isna().all()
    assert result["liq_adv_2d"].isna().all()
    assert result["liq_rel_volume_2d"].isna().all()
    assert not result["liq_is_price_eligible"].any()
    assert not result["liq_is_adv20_eligible"].any()
    assert not result["liq_is_liquid"].any()


def test_turnover_proxy_uses_shares_outstanding_when_available() -> None:
    prices = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "closeadj": [10.0, 11.0],
            "volume": [100.0, 150.0],
            "shareswa": [1000.0, 0.0],
        }
    )

    result = add_volume_liquidity_features(
        prices,
        shares_column="shareswa",
        windows=(1,),
    )

    assert result["liq_turnover"].iloc[0] == pytest.approx(0.10)
    assert pd.isna(result["liq_turnover"].iloc[1])


def test_turnover_proxy_can_use_market_cap_and_handles_zero_price() -> None:
    prices = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "closeadj": [10.0, 0.0],
            "volume": [100.0, 150.0],
            "marketcap": [1000.0, 2000.0],
        }
    )

    result = add_volume_liquidity_features(
        prices,
        marketcap_column="marketcap",
        windows=(1,),
    )

    assert result["liq_turnover"].iloc[0] == pytest.approx(1.0)
    assert pd.isna(result["liq_turnover"].iloc[1])


def test_panel_liquidity_features_do_not_cross_ticker_boundaries() -> None:
    start = date(2026, 1, 1)
    rows = []
    for offset in range(3):
        rows.append(("AAPL", start + timedelta(days=offset), 10.0, 100.0))
        rows.append(("MSFT", start + timedelta(days=offset), 20.0, 200.0))
    panel = pd.DataFrame(rows, columns=["ticker", "date", "closeadj", "volume"])

    result = add_volume_liquidity_features_for_panel(panel, windows=(2,))

    aapl = result[result["ticker"] == "AAPL"].reset_index(drop=True)
    msft = result[result["ticker"] == "MSFT"].reset_index(drop=True)
    assert pd.isna(aapl["liq_adv_2d"].iloc[0])
    assert pd.isna(msft["liq_adv_2d"].iloc[0])
    assert aapl["liq_adv_2d"].iloc[1] == pytest.approx(1000.0)
    assert msft["liq_adv_2d"].iloc[1] == pytest.approx(4000.0)


def test_liquidity_features_reject_invalid_windows() -> None:
    with pytest.raises(ValueError, match="windows"):
        add_volume_liquidity_features(liquidity_frame(), windows=(20, 0))
