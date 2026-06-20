from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.experiments.volatility_risk_features import (
    add_volatility_risk_features,
    add_volatility_risk_features_for_panel,
)


def risk_frame(close_values: list[float]) -> pd.DataFrame:
    start = date(2026, 1, 1)
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=offset) for offset in range(len(close_values))],
            "closeadj": close_values,
        }
    )


def test_constant_price_has_zero_realized_and_downside_volatility() -> None:
    prices = risk_frame([100.0, 100.0, 100.0, 100.0])
    spy = pd.DataFrame(
        {
            "date": prices["date"],
            "market_return": [0.0, 0.01, -0.01, 0.02],
        }
    )

    result = add_volatility_risk_features(
        prices,
        market_proxy=spy,
        market_return_column="market_return",
        windows=(2,),
    )

    assert result["risk_realized_vol_2d"].iloc[2] == pytest.approx(0.0)
    assert result["risk_downside_vol_2d"].iloc[2] == pytest.approx(0.0)
    assert result["risk_beta_spy_2d"].iloc[2] == pytest.approx(0.0)
    assert result["risk_idio_vol_spy_2d"].iloc[2] == pytest.approx(0.0)
    assert result["risk_max_drawdown_2d"].iloc[1] == pytest.approx(0.0)


def test_missing_market_proxy_produces_null_beta_and_idio_columns() -> None:
    result = add_volatility_risk_features(risk_frame([100.0, 101.0, 103.0]), windows=(2,))

    assert result["risk_beta_spy_2d"].isna().all()
    assert result["risk_idio_vol_spy_2d"].isna().all()
    assert result["risk_realized_vol_2d"].notna().iloc[-1]


def test_short_history_keeps_warmup_features_null() -> None:
    result = add_volatility_risk_features(risk_frame([100.0, 101.0, 102.0]), windows=(5,))

    assert result["risk_realized_vol_5d"].isna().all()
    assert result["risk_downside_vol_5d"].isna().all()
    assert result["risk_max_drawdown_5d"].isna().all()
    assert result["risk_beta_spy_5d"].isna().all()


def test_beta_uses_trailing_exact_date_market_returns_without_future_leakage() -> None:
    prices = risk_frame([100.0, 110.0, 121.0, 133.1, 146.41])
    spy = pd.DataFrame(
        {
            "date": prices["date"],
            "market_return": [0.0, 0.05, 0.10, 0.15, 99.0],
        }
    )
    changed_future_spy = spy.copy()
    changed_future_spy.loc[4, "market_return"] = -99.0

    result = add_volatility_risk_features(
        prices,
        market_proxy=spy,
        market_return_column="market_return",
        windows=(2,),
    )
    changed_result = add_volatility_risk_features(
        prices,
        market_proxy=changed_future_spy,
        market_return_column="market_return",
        windows=(2,),
    )

    assert result["risk_beta_spy_2d"].iloc[3] == pytest.approx(
        changed_result["risk_beta_spy_2d"].iloc[3]
    )
    assert result["risk_beta_spy_2d"].iloc[3] == pytest.approx(0.0)


def test_missing_market_dates_are_not_forward_filled() -> None:
    prices = risk_frame([100.0, 110.0, 121.0])
    spy = pd.DataFrame(
        {
            "date": [prices["date"].iloc[0], prices["date"].iloc[1]],
            "market_return": [0.0, 0.05],
        }
    )

    result = add_volatility_risk_features(
        prices,
        market_proxy=spy,
        market_return_column="market_return",
        windows=(2,),
    )

    assert pd.isna(result["risk_beta_spy_2d"].iloc[2])


def test_recent_max_drawdown_is_worst_drawdown_inside_trailing_window() -> None:
    result = add_volatility_risk_features(
        risk_frame([100.0, 110.0, 90.0, 95.0]),
        windows=(3,),
    )

    assert result["risk_max_drawdown_3d"].iloc[:2].isna().all()
    assert result["risk_max_drawdown_3d"].iloc[2] == pytest.approx(90.0 / 110.0 - 1.0)
    assert result["risk_max_drawdown_3d"].iloc[3] == pytest.approx(90.0 / 110.0 - 1.0)


def test_panel_risk_features_do_not_cross_ticker_boundaries() -> None:
    start = date(2026, 1, 1)
    rows = []
    for offset in range(4):
        rows.append(("AAPL", start + timedelta(days=offset), 100.0 + offset))
        rows.append(("MSFT", start + timedelta(days=offset), 200.0 + offset**2))
    panel = pd.DataFrame(rows, columns=["ticker", "date", "closeadj"])

    result = add_volatility_risk_features_for_panel(panel, windows=(2,))

    aapl = result[result["ticker"] == "AAPL"].reset_index(drop=True)
    msft = result[result["ticker"] == "MSFT"].reset_index(drop=True)
    assert aapl["risk_realized_vol_2d"].iloc[:2].isna().all()
    assert msft["risk_realized_vol_2d"].iloc[:2].isna().all()
    assert aapl["risk_realized_vol_2d"].iloc[2] != msft["risk_realized_vol_2d"].iloc[2]


def test_volatility_risk_features_reject_invalid_windows() -> None:
    with pytest.raises(ValueError, match="windows"):
        add_volatility_risk_features(risk_frame([100.0, 101.0]), windows=(21, 0))
