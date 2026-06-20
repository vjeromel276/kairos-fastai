"""Price behavior features for multi-factor experiments."""

from __future__ import annotations

import pandas as pd


DEFAULT_RETURN_PERIODS = (1, 5, 21, 63, 126, 252)
DEFAULT_MA_WINDOWS = (21, 63, 252)
DEFAULT_DRAWDOWN_WINDOWS = (252,)
DEFAULT_SHORT_REVERSAL_PERIOD = 5


def validate_positive_periods(periods: tuple[int, ...], name: str) -> tuple[int, ...]:
    if any(period < 1 for period in periods):
        raise ValueError(f"{name} must contain positive integers")
    return tuple(dict.fromkeys(periods))


def add_price_behavior_features(
    prices: pd.DataFrame,
    close_column: str = "closeadj",
    date_column: str = "date",
    return_periods: tuple[int, ...] = DEFAULT_RETURN_PERIODS,
    ma_windows: tuple[int, ...] = DEFAULT_MA_WINDOWS,
    drawdown_windows: tuple[int, ...] = DEFAULT_DRAWDOWN_WINDOWS,
    short_reversal_period: int = DEFAULT_SHORT_REVERSAL_PERIOD,
) -> pd.DataFrame:
    """Return a copy of one ticker's prices with price behavior features."""
    if close_column not in prices.columns:
        raise KeyError(f"missing close column: {close_column}")
    if date_column not in prices.columns:
        raise KeyError(f"missing date column: {date_column}")
    if short_reversal_period < 1:
        raise ValueError("short_reversal_period must be >= 1")

    clean_return_periods = validate_positive_periods(return_periods, "return_periods")
    clean_ma_windows = validate_positive_periods(ma_windows, "ma_windows")
    clean_drawdown_windows = validate_positive_periods(drawdown_windows, "drawdown_windows")

    result = prices.sort_values(date_column).copy()
    close = pd.to_numeric(result[close_column], errors="coerce")

    for period in clean_return_periods:
        result[f"px_return_{period}d"] = close / close.shift(period) - 1.0

    for window in clean_ma_windows:
        moving_average = close.rolling(window=window, min_periods=window).mean()
        result[f"px_ma_dist_{window}d"] = close / moving_average - 1.0

    for window in clean_drawdown_windows:
        rolling_high = close.rolling(window=window, min_periods=window).max()
        result[f"px_drawdown_{window}d"] = close / rolling_high - 1.0

    reversal_source = f"px_return_{short_reversal_period}d"
    if reversal_source not in result.columns:
        result[reversal_source] = close / close.shift(short_reversal_period) - 1.0
    result[f"px_short_reversal_{short_reversal_period}d"] = -result[reversal_source]
    return result


def add_price_behavior_features_for_panel(
    prices: pd.DataFrame,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "closeadj",
    return_periods: tuple[int, ...] = DEFAULT_RETURN_PERIODS,
    ma_windows: tuple[int, ...] = DEFAULT_MA_WINDOWS,
    drawdown_windows: tuple[int, ...] = DEFAULT_DRAWDOWN_WINDOWS,
    short_reversal_period: int = DEFAULT_SHORT_REVERSAL_PERIOD,
) -> pd.DataFrame:
    """Return a panel copy with price behavior features computed per ticker."""
    if ticker_column not in prices.columns:
        raise KeyError(f"missing ticker column: {ticker_column}")

    parts = [
        add_price_behavior_features(
            group,
            close_column=close_column,
            date_column=date_column,
            return_periods=return_periods,
            ma_windows=ma_windows,
            drawdown_windows=drawdown_windows,
            short_reversal_period=short_reversal_period,
        )
        for _, group in prices.groupby(ticker_column, sort=False)
    ]
    if not parts:
        return prices.copy()
    return pd.concat(parts, ignore_index=True).sort_values(
        [ticker_column, date_column],
    ).reset_index(drop=True)
