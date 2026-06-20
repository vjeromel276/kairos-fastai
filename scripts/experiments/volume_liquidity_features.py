"""Volume and liquidity features for multi-factor experiments."""

from __future__ import annotations

import pandas as pd


DEFAULT_WINDOWS = (20, 60)
DEFAULT_MIN_PRICE = 5.0
DEFAULT_MIN_ADV_20 = 1_000_000.0


def validate_windows(windows: tuple[int, ...]) -> tuple[int, ...]:
    if any(window < 1 for window in windows):
        raise ValueError("windows must contain positive integers")
    return tuple(dict.fromkeys(windows))


def numeric_column_or_nan(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(float("nan"), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def add_volume_liquidity_features(
    prices: pd.DataFrame,
    close_column: str = "closeadj",
    volume_column: str = "volume",
    date_column: str = "date",
    shares_column: str | None = None,
    marketcap_column: str | None = None,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    min_price: float = DEFAULT_MIN_PRICE,
    min_adv_20: float = DEFAULT_MIN_ADV_20,
) -> pd.DataFrame:
    """Return a copy of one ticker's rows with volume/liquidity features."""
    if date_column not in prices.columns:
        raise KeyError(f"missing date column: {date_column}")

    clean_windows = validate_windows(windows)
    result = prices.sort_values(date_column).copy()
    close = numeric_column_or_nan(result, close_column)
    volume = numeric_column_or_nan(result, volume_column)

    result["liq_dollar_volume"] = close * volume
    result["liq_is_price_eligible"] = close >= min_price

    for window in clean_windows:
        volume_average = volume.rolling(window=window, min_periods=window).mean()
        dollar_volume_average = result["liq_dollar_volume"].rolling(
            window=window,
            min_periods=window,
        ).mean()
        result[f"liq_volume_avg_{window}d"] = volume_average
        result[f"liq_adv_{window}d"] = dollar_volume_average
        result[f"liq_rel_volume_{window}d"] = volume / volume_average

    if "liq_adv_20d" in result.columns:
        result["liq_is_adv20_eligible"] = result["liq_adv_20d"] >= min_adv_20
    else:
        result["liq_is_adv20_eligible"] = False

    result["liq_turnover"] = turnover_proxy(
        result,
        close=close,
        volume=volume,
        shares_column=shares_column,
        marketcap_column=marketcap_column,
    )
    result["liq_is_liquid"] = (
        result["liq_is_price_eligible"].fillna(False)
        & result["liq_is_adv20_eligible"].fillna(False)
    )
    return result


def turnover_proxy(
    df: pd.DataFrame,
    close: pd.Series,
    volume: pd.Series,
    shares_column: str | None = None,
    marketcap_column: str | None = None,
) -> pd.Series:
    """Estimate turnover from shares outstanding or market cap when available."""
    if shares_column and shares_column in df.columns:
        shares = pd.to_numeric(df[shares_column], errors="coerce")
        return volume / shares.where(shares > 0)

    if marketcap_column and marketcap_column in df.columns:
        marketcap = pd.to_numeric(df[marketcap_column], errors="coerce")
        implied_shares = marketcap / close.where(close > 0)
        return volume / implied_shares.where(implied_shares > 0)

    return pd.Series(float("nan"), index=df.index, dtype="float64")


def add_volume_liquidity_features_for_panel(
    prices: pd.DataFrame,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "closeadj",
    volume_column: str = "volume",
    shares_column: str | None = None,
    marketcap_column: str | None = None,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    min_price: float = DEFAULT_MIN_PRICE,
    min_adv_20: float = DEFAULT_MIN_ADV_20,
) -> pd.DataFrame:
    """Return a panel copy with liquidity features computed per ticker."""
    if ticker_column not in prices.columns:
        raise KeyError(f"missing ticker column: {ticker_column}")

    parts = [
        add_volume_liquidity_features(
            group,
            close_column=close_column,
            volume_column=volume_column,
            date_column=date_column,
            shares_column=shares_column,
            marketcap_column=marketcap_column,
            windows=windows,
            min_price=min_price,
            min_adv_20=min_adv_20,
        )
        for _, group in prices.groupby(ticker_column, sort=False)
    ]
    if not parts:
        return prices.copy()
    return pd.concat(parts, ignore_index=True).sort_values(
        [ticker_column, date_column],
    ).reset_index(drop=True)
