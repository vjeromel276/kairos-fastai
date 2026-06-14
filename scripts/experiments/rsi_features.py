"""Pure pandas RSI feature helpers for RSI experiments."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Sequence

import pandas as pd


DEFAULT_RSI_WINDOW = 14
DEFAULT_SLOPE_PERIODS = (3, 5, 10, 20)
DEFAULT_EMA_SPANS = (5, 10, 20)
DEFAULT_EMA_SPREADS = ((5, 10), (5, 20))


def _validate_positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0

    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def calculate_rsi(close: pd.Series, window: int = DEFAULT_RSI_WINDOW) -> pd.Series:
    """
    Calculate Wilder-style RSI from a close-price series.

    The first `window` rows are null because RSI needs `window` completed price
    changes. If missing values interrupt the price path, the warmup restarts and
    RSI remains null until another complete window of valid changes is present.
    A window with no gain and no loss is treated as neutral RSI 50.
    """
    _validate_positive_int(window, "window")

    close_values = pd.to_numeric(close, errors="coerce")
    delta = close_values.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)

    rsi = pd.Series(float("nan"), index=close.index, dtype="float64", name=f"rsi_{window}")
    warmup_gains: list[float] = []
    warmup_losses: list[float] = []
    avg_gain: float | None = None
    avg_loss: float | None = None

    for pos in range(1, len(close_values)):
        gain = gains.iloc[pos]
        loss = losses.iloc[pos]

        if pd.isna(gain) or pd.isna(loss):
            warmup_gains = []
            warmup_losses = []
            avg_gain = None
            avg_loss = None
            continue

        gain_float = float(gain)
        loss_float = float(loss)

        if avg_gain is None or avg_loss is None:
            warmup_gains.append(gain_float)
            warmup_losses.append(loss_float)
            if len(warmup_gains) < window:
                continue

            avg_gain = sum(warmup_gains) / window
            avg_loss = sum(warmup_losses) / window
        else:
            avg_gain = ((avg_gain * (window - 1)) + gain_float) / window
            avg_loss = ((avg_loss * (window - 1)) + loss_float) / window

        rsi.iloc[pos] = _rsi_from_averages(avg_gain, avg_loss)

    return rsi


def add_rsi_slope_features(
    df: pd.DataFrame,
    rsi_column: str = "rsi_14",
    periods: Sequence[int] = DEFAULT_SLOPE_PERIODS,
    prefix: str = "rsi_slope",
) -> pd.DataFrame:
    """Return a copy of `df` with RSI slope features added."""
    if rsi_column not in df.columns:
        raise KeyError(f"missing RSI column: {rsi_column}")
    for period in periods:
        _validate_positive_int(period, "period")

    result = df.copy()
    for period in periods:
        result[f"{prefix}_{period}"] = result[rsi_column] - result[rsi_column].shift(period)
    return result


def add_rsi_ema_features(
    df: pd.DataFrame,
    rsi_column: str = "rsi_14",
    spans: Sequence[int] = DEFAULT_EMA_SPANS,
    spreads: Iterable[tuple[int, int]] = DEFAULT_EMA_SPREADS,
    prefix: str = "rsi_ema",
) -> pd.DataFrame:
    """Return a copy of `df` with RSI EMA and EMA-spread features added."""
    if rsi_column not in df.columns:
        raise KeyError(f"missing RSI column: {rsi_column}")
    for span in spans:
        _validate_positive_int(span, "span")

    result = df.copy()
    span_set = set(spans)
    for span in spans:
        result[f"{prefix}_{span}"] = result[rsi_column].ewm(span=span, adjust=False).mean()

    for fast_span, slow_span in spreads:
        if fast_span not in span_set or slow_span not in span_set:
            raise ValueError(
                f"EMA spread ({fast_span}, {slow_span}) requires both spans to be present"
            )
        result[f"{prefix}_{fast_span}_minus_{slow_span}"] = (
            result[f"{prefix}_{fast_span}"] - result[f"{prefix}_{slow_span}"]
        )

    return result


def add_rsi_recency_features(
    df: pd.DataFrame,
    close_column: str = "closeadj",
    rsi_window: int = DEFAULT_RSI_WINDOW,
    slope_periods: Sequence[int] = DEFAULT_SLOPE_PERIODS,
    ema_spans: Sequence[int] = DEFAULT_EMA_SPANS,
    ema_spreads: Iterable[tuple[int, int]] = DEFAULT_EMA_SPREADS,
) -> pd.DataFrame:
    """Return a copy of `df` with RSI, slope, and RSI EMA recency features."""
    if close_column not in df.columns:
        raise KeyError(f"missing close column: {close_column}")

    result = df.copy()
    rsi_column = f"rsi_{rsi_window}"
    result[rsi_column] = calculate_rsi(result[close_column], window=rsi_window)
    result = add_rsi_slope_features(result, rsi_column=rsi_column, periods=slope_periods)
    return add_rsi_ema_features(
        result,
        rsi_column=rsi_column,
        spans=ema_spans,
        spreads=ema_spreads,
    )
