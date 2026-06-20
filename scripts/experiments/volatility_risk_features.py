"""Volatility and risk features for multi-factor experiments.

SPY is the default documented market proxy for beta and idiosyncratic
volatility features.
"""

from __future__ import annotations

import math

import pandas as pd


DEFAULT_WINDOWS = (21, 63, 252)
DEFAULT_MARKET_SUFFIX = "spy"
TRADING_DAYS_PER_YEAR = 252.0


def validate_windows(windows: tuple[int, ...]) -> tuple[int, ...]:
    if any(window < 1 for window in windows):
        raise ValueError("windows must contain positive integers")
    return tuple(dict.fromkeys(windows))


def rolling_max_drawdown(close: pd.Series, window: int) -> pd.Series:
    """Return the worst peak-to-trough drawdown within each trailing window."""

    def window_max_drawdown(values: pd.Series) -> float:
        running_high = values.cummax()
        drawdowns = values / running_high - 1.0
        return float(drawdowns.min())

    return close.rolling(window=window, min_periods=window).apply(
        window_max_drawdown,
        raw=False,
    )


def market_returns_for_dates(
    dates: pd.Series,
    market_proxy: pd.DataFrame | None,
    close_column: str,
    date_column: str,
    market_return_column: str | None = None,
) -> pd.Series | None:
    """Return exact-date market returns aligned to `dates`, without forward fill."""
    if market_proxy is None:
        return None
    if date_column not in market_proxy.columns:
        raise KeyError(f"missing market date column: {date_column}")

    market = (
        market_proxy.sort_values(date_column)
        .drop_duplicates(subset=[date_column], keep="last")
        .copy()
    )
    if market_return_column:
        if market_return_column not in market.columns:
            raise KeyError(f"missing market return column: {market_return_column}")
        market["__market_return"] = pd.to_numeric(
            market[market_return_column],
            errors="coerce",
        )
    else:
        if close_column not in market.columns:
            raise KeyError(f"missing market close column: {close_column}")
        close = pd.to_numeric(market[close_column], errors="coerce")
        market["__market_return"] = close / close.shift(1) - 1.0

    aligned = pd.DataFrame({date_column: dates}).merge(
        market[[date_column, "__market_return"]],
        on=date_column,
        how="left",
    )
    return aligned["__market_return"]


def add_volatility_risk_features(
    prices: pd.DataFrame,
    market_proxy: pd.DataFrame | None = None,
    close_column: str = "closeadj",
    date_column: str = "date",
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    market_suffix: str = DEFAULT_MARKET_SUFFIX,
    market_return_column: str | None = None,
    annualization_factor: float = TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Return a copy of one ticker's rows with volatility/risk features."""
    if close_column not in prices.columns:
        raise KeyError(f"missing close column: {close_column}")
    if date_column not in prices.columns:
        raise KeyError(f"missing date column: {date_column}")
    if annualization_factor <= 0:
        raise ValueError("annualization_factor must be positive")

    clean_windows = validate_windows(windows)
    result = prices.sort_values(date_column).copy()
    close = pd.to_numeric(result[close_column], errors="coerce")
    returns = close / close.shift(1) - 1.0
    downside_returns = returns.clip(upper=0.0)
    annualizer = math.sqrt(annualization_factor)

    market_returns = market_returns_for_dates(
        result[date_column],
        market_proxy,
        close_column=close_column,
        date_column=date_column,
        market_return_column=market_return_column,
    )
    if market_returns is not None:
        market_returns = pd.Series(
            pd.to_numeric(market_returns, errors="coerce").to_numpy(),
            index=result.index,
            dtype="float64",
        )

    for window in clean_windows:
        result[f"risk_realized_vol_{window}d"] = (
            returns.rolling(window=window, min_periods=window).std(ddof=0)
            * annualizer
        )
        result[f"risk_downside_vol_{window}d"] = (
            downside_returns.rolling(window=window, min_periods=window).std(ddof=0)
            * annualizer
        )
        result[f"risk_max_drawdown_{window}d"] = rolling_max_drawdown(close, window)

        beta_column = f"risk_beta_{market_suffix}_{window}d"
        idio_column = f"risk_idio_vol_{market_suffix}_{window}d"
        if market_returns is None:
            result[beta_column] = pd.Series(
                float("nan"),
                index=result.index,
                dtype="float64",
            )
            result[idio_column] = pd.Series(
                float("nan"),
                index=result.index,
                dtype="float64",
            )
            continue

        asset_var = returns.rolling(window=window, min_periods=window).var(ddof=0)
        market_var = market_returns.rolling(window=window, min_periods=window).var(
            ddof=0,
        )
        covariance = returns.rolling(window=window, min_periods=window).cov(
            market_returns,
            ddof=0,
        )
        result[beta_column] = covariance / market_var.where(market_var > 0)
        idio_var = asset_var - (covariance**2 / market_var.where(market_var > 0))
        result[idio_column] = idio_var.clip(lower=0.0).pow(0.5) * annualizer

    return result


def add_volatility_risk_features_for_panel(
    prices: pd.DataFrame,
    market_proxy: pd.DataFrame | None = None,
    ticker_column: str = "ticker",
    date_column: str = "date",
    close_column: str = "closeadj",
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    market_suffix: str = DEFAULT_MARKET_SUFFIX,
    market_return_column: str | None = None,
    annualization_factor: float = TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Return a panel copy with volatility/risk features computed per ticker."""
    if ticker_column not in prices.columns:
        raise KeyError(f"missing ticker column: {ticker_column}")

    parts = [
        add_volatility_risk_features(
            group,
            market_proxy=market_proxy,
            close_column=close_column,
            date_column=date_column,
            windows=windows,
            market_suffix=market_suffix,
            market_return_column=market_return_column,
            annualization_factor=annualization_factor,
        )
        for _, group in prices.groupby(ticker_column, sort=False)
    ]
    if not parts:
        return prices.copy()
    return pd.concat(parts, ignore_index=True).sort_values(
        [ticker_column, date_column],
    ).reset_index(drop=True)
