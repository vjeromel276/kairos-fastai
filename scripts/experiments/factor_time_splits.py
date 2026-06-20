"""Time split helpers for multi-factor panel experiments."""

from __future__ import annotations

import pandas as pd

from scripts.experiments.rsi_time_splits import EmbargoUnit, default_embargo, make_time_splits


DEFAULT_FACTOR_FEATURE_LOOKBACK_DAYS = 252
DEFAULT_FACTOR_PREDICTION_HORIZON_DAYS = 21


def default_factor_embargo(
    feature_lookback_days: int = DEFAULT_FACTOR_FEATURE_LOOKBACK_DAYS,
    prediction_horizon_days: int = DEFAULT_FACTOR_PREDICTION_HORIZON_DAYS,
) -> int:
    """Return the default embargo for a factor experiment."""
    return default_embargo(
        feature_lookback_days=feature_lookback_days,
        prediction_horizon_days=prediction_horizon_days,
    )


def make_factor_time_splits(
    df: pd.DataFrame,
    train_end: object,
    validation_end: object,
    test_end: object,
    train_start: object | None = None,
    validation_start: object | None = None,
    test_start: object | None = None,
    date_column: str = "date",
    embargo: int | None = None,
    embargo_unit: EmbargoUnit = "trading",
    feature_lookback_days: int = DEFAULT_FACTOR_FEATURE_LOOKBACK_DAYS,
    prediction_horizon_days: int = DEFAULT_FACTOR_PREDICTION_HORIZON_DAYS,
) -> dict[str, pd.DataFrame]:
    """
    Split a factor panel into chronological train/validation/test windows.

    The split is global by date across all tickers. Rows are never shuffled.
    """
    return make_time_splits(
        df,
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=test_end,
        date_column=date_column,
        embargo=embargo,
        embargo_unit=embargo_unit,
        feature_lookback_days=feature_lookback_days,
        prediction_horizon_days=prediction_horizon_days,
    )
