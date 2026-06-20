"""Date-level regime context features for multi-factor experiments."""

from __future__ import annotations

import math

import pandas as pd


DEFAULT_TREND_WINDOWS = (50, 200)
DEFAULT_VOL_WINDOWS = (21, 63)
DEFAULT_DRAWDOWN_WINDOW = 252
DEFAULT_RETURN_WINDOW = 21
TRADING_DAYS_PER_YEAR = 252.0


def validate_windows(windows: tuple[int, ...], name: str) -> tuple[int, ...]:
    if any(window < 1 for window in windows):
        raise ValueError(f"{name} must contain positive integers")
    return tuple(dict.fromkeys(windows))


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.where(denominator != 0)


def build_spy_regime_features(
    spy_prices: pd.DataFrame,
    date_column: str = "date",
    close_column: str = "closeadj",
    trend_windows: tuple[int, ...] = DEFAULT_TREND_WINDOWS,
    vol_windows: tuple[int, ...] = DEFAULT_VOL_WINDOWS,
    drawdown_window: int = DEFAULT_DRAWDOWN_WINDOW,
    return_window: int = DEFAULT_RETURN_WINDOW,
    annualization_factor: float = TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Build SPY date-level regime features using trailing data through date T."""
    if date_column not in spy_prices.columns:
        raise KeyError(f"missing SPY date column: {date_column}")
    if close_column not in spy_prices.columns:
        raise KeyError(f"missing SPY close column: {close_column}")
    if drawdown_window < 1:
        raise ValueError("drawdown_window must be >= 1")
    if return_window < 1:
        raise ValueError("return_window must be >= 1")
    if annualization_factor <= 0:
        raise ValueError("annualization_factor must be positive")

    clean_trend_windows = validate_windows(trend_windows, "trend_windows")
    clean_vol_windows = validate_windows(vol_windows, "vol_windows")
    result = (
        spy_prices[[date_column, close_column]]
        .sort_values(date_column)
        .drop_duplicates(subset=[date_column], keep="last")
        .copy()
    )
    close = pd.to_numeric(result[close_column], errors="coerce")
    returns = close / close.shift(1) - 1.0
    annualizer = math.sqrt(annualization_factor)

    result[f"regime_spy_return_{return_window}d"] = (
        close / close.shift(return_window) - 1.0
    )
    for window in clean_trend_windows:
        moving_average = close.rolling(window=window, min_periods=window).mean()
        trend = close / moving_average - 1.0
        result[f"regime_spy_trend_{window}d"] = trend
        result[f"regime_spy_above_ma_{window}d"] = (
            trend.gt(0).astype("float64").where(trend.notna())
        )

    for window in clean_vol_windows:
        result[f"regime_spy_realized_vol_{window}d"] = (
            returns.rolling(window=window, min_periods=window).std(ddof=0)
            * annualizer
        )

    rolling_high = close.rolling(window=drawdown_window, min_periods=drawdown_window).max()
    result[f"regime_spy_drawdown_{drawdown_window}d"] = close / rolling_high - 1.0

    shortest_vol_window = min(clean_vol_windows)
    result[f"regime_spy_risk_on_score_{return_window}d"] = safe_divide(
        result[f"regime_spy_return_{return_window}d"],
        result[f"regime_spy_realized_vol_{shortest_vol_window}d"],
    )
    return result.drop(columns=[close_column])


def build_breadth_features(
    panel: pd.DataFrame,
    breadth_columns: tuple[str, ...],
    date_column: str = "date",
) -> pd.DataFrame:
    """Build same-date market breadth proxies from already-known panel features."""
    if date_column not in panel.columns:
        raise KeyError(f"missing panel date column: {date_column}")
    missing = sorted(set(breadth_columns) - set(panel.columns))
    if missing:
        raise KeyError(f"panel missing breadth columns: {', '.join(missing)}")

    dates = panel[[date_column]].drop_duplicates().copy()
    for column in breadth_columns:
        numeric = pd.to_numeric(panel[column], errors="coerce")
        available = numeric.notna()
        positive = numeric > 0
        breadth = positive.where(available).groupby(panel[date_column]).mean()
        dates = dates.merge(
            breadth.rename(f"regime_breadth_{column}_positive"),
            on=date_column,
            how="left",
        )
    return dates.sort_values(date_column).reset_index(drop=True)


def add_regime_context_features(
    panel: pd.DataFrame,
    spy_prices: pd.DataFrame,
    date_column: str = "date",
    close_column: str = "closeadj",
    trend_windows: tuple[int, ...] = DEFAULT_TREND_WINDOWS,
    vol_windows: tuple[int, ...] = DEFAULT_VOL_WINDOWS,
    drawdown_window: int = DEFAULT_DRAWDOWN_WINDOW,
    return_window: int = DEFAULT_RETURN_WINDOW,
    breadth_columns: tuple[str, ...] = (),
    annualization_factor: float = TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Join exact-date regime features to every ticker row for the same date."""
    if date_column not in panel.columns:
        raise KeyError(f"missing panel date column: {date_column}")

    result = panel.copy()
    result["__panel_date"] = pd.to_datetime(result[date_column], errors="coerce")
    regime = build_spy_regime_features(
        spy_prices,
        date_column=date_column,
        close_column=close_column,
        trend_windows=trend_windows,
        vol_windows=vol_windows,
        drawdown_window=drawdown_window,
        return_window=return_window,
        annualization_factor=annualization_factor,
    )
    regime["__regime_date"] = pd.to_datetime(regime[date_column], errors="coerce")
    result = result.merge(
        regime.drop(columns=[date_column]),
        left_on="__panel_date",
        right_on="__regime_date",
        how="left",
    )

    if breadth_columns:
        breadth = build_breadth_features(
            panel,
            breadth_columns=breadth_columns,
            date_column=date_column,
        )
        breadth["__breadth_date"] = pd.to_datetime(breadth[date_column], errors="coerce")
        result = result.merge(
            breadth.drop(columns=[date_column]),
            left_on="__panel_date",
            right_on="__breadth_date",
            how="left",
        )

    drop_columns = [
        column
        for column in ("__panel_date", "__regime_date", "__breadth_date")
        if column in result.columns
    ]
    return result.drop(columns=drop_columns).sort_values(date_column).reset_index(drop=True)
