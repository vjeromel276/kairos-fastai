"""Time-based split helpers for RSI experiments."""

from __future__ import annotations

from typing import Literal

import pandas as pd


DEFAULT_FEATURE_LOOKBACK_DAYS = 63
DEFAULT_PREDICTION_HORIZON_DAYS = 5
EmbargoUnit = Literal["calendar", "trading"]


def default_embargo(
    feature_lookback_days: int = DEFAULT_FEATURE_LOOKBACK_DAYS,
    prediction_horizon_days: int = DEFAULT_PREDICTION_HORIZON_DAYS,
) -> int:
    """Return the default embargo length for an experiment."""
    if feature_lookback_days < 0:
        raise ValueError("feature_lookback_days must be >= 0")
    if prediction_horizon_days < 0:
        raise ValueError("prediction_horizon_days must be >= 0")
    return max(feature_lookback_days, prediction_horizon_days)


def coerce_timestamp(value: object, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"{name} must be a valid date")
    return timestamp


def validate_date_boundaries(
    train_end: object,
    validation_end: object,
    test_end: object,
    train_start: object | None = None,
    validation_start: object | None = None,
    test_start: object | None = None,
) -> dict[str, pd.Timestamp | None]:
    """Validate and normalize split boundary dates."""
    boundaries = {
        "train_start": coerce_timestamp(train_start, "train_start") if train_start else None,
        "train_end": coerce_timestamp(train_end, "train_end"),
        "validation_start": (
            coerce_timestamp(validation_start, "validation_start")
            if validation_start
            else None
        ),
        "validation_end": coerce_timestamp(validation_end, "validation_end"),
        "test_start": coerce_timestamp(test_start, "test_start") if test_start else None,
        "test_end": coerce_timestamp(test_end, "test_end"),
    }

    if boundaries["train_start"] and boundaries["train_start"] > boundaries["train_end"]:
        raise ValueError("train_start must be <= train_end")
    if boundaries["validation_start"] and (
        boundaries["validation_start"] > boundaries["validation_end"]
    ):
        raise ValueError("validation_start must be <= validation_end")
    if boundaries["test_start"] and boundaries["test_start"] > boundaries["test_end"]:
        raise ValueError("test_start must be <= test_end")
    if not boundaries["train_end"] < boundaries["validation_end"] < boundaries["test_end"]:
        raise ValueError("expected train_end < validation_end < test_end")

    return boundaries


def calendar_embargo_cutoff(boundary: pd.Timestamp, embargo: int) -> pd.Timestamp:
    return boundary + pd.Timedelta(days=embargo)


def trading_embargo_cutoff(
    dates: pd.Series,
    boundary: pd.Timestamp,
    embargo: int,
) -> pd.Timestamp:
    future_dates = (
        pd.Series(pd.to_datetime(dates).dropna().unique())
        .sort_values(ignore_index=True)
    )
    future_dates = future_dates[future_dates > boundary]
    if embargo == 0:
        return boundary
    if len(future_dates) <= embargo:
        return pd.Timestamp.max
    return pd.Timestamp(future_dates.iloc[embargo - 1])


def embargo_cutoff(
    dates: pd.Series,
    boundary: pd.Timestamp,
    embargo: int,
    unit: EmbargoUnit,
) -> pd.Timestamp:
    if embargo < 0:
        raise ValueError("embargo must be >= 0")
    if unit == "calendar":
        return calendar_embargo_cutoff(boundary, embargo)
    if unit == "trading":
        return trading_embargo_cutoff(dates, boundary, embargo)
    raise ValueError("embargo_unit must be 'calendar' or 'trading'")


def make_time_splits(
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
    feature_lookback_days: int = DEFAULT_FEATURE_LOOKBACK_DAYS,
    prediction_horizon_days: int = DEFAULT_PREDICTION_HORIZON_DAYS,
) -> dict[str, pd.DataFrame]:
    """
    Split rows into train/validation/test windows with embargo gaps.

    Rows retain their original relative order. The helper does not shuffle.
    """
    if date_column not in df.columns:
        raise KeyError(f"missing date column: {date_column}")

    split_embargo = (
        default_embargo(feature_lookback_days, prediction_horizon_days)
        if embargo is None
        else embargo
    )
    boundaries = validate_date_boundaries(
        train_start=train_start,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        test_start=test_start,
        test_end=test_end,
    )

    dates = pd.to_datetime(df[date_column])
    validation_cutoff = embargo_cutoff(
        dates,
        boundaries["train_end"],
        split_embargo,
        embargo_unit,
    )
    test_cutoff = embargo_cutoff(
        dates,
        boundaries["validation_end"],
        split_embargo,
        embargo_unit,
    )

    train_mask = dates <= boundaries["train_end"]
    if boundaries["train_start"] is not None:
        train_mask &= dates >= boundaries["train_start"]

    validation_mask = (dates > validation_cutoff) & (dates <= boundaries["validation_end"])
    if boundaries["validation_start"] is not None:
        validation_mask &= dates >= boundaries["validation_start"]

    test_mask = (dates > test_cutoff) & (dates <= boundaries["test_end"])
    if boundaries["test_start"] is not None:
        test_mask &= dates >= boundaries["test_start"]

    return {
        "train": df.loc[train_mask].copy(),
        "validation": df.loc[validation_mask].copy(),
        "test": df.loc[test_mask].copy(),
    }
