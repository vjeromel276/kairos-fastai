from __future__ import annotations

import math

import pandas as pd
import pytest

from scripts.experiments.rsi_features import (
    add_rsi_ema_features,
    add_rsi_recency_features,
    add_rsi_slope_features,
    calculate_rsi,
)


def assert_nan_prefix(series: pd.Series, expected_nulls: int) -> None:
    assert series.iloc[:expected_nulls].isna().all()


def test_calculate_rsi_matches_known_wilder_values() -> None:
    close = pd.Series([10, 11, 13, 12, 14, 13, 15], dtype="float64")

    rsi = calculate_rsi(close, window=3)

    assert rsi.name == "rsi_3"
    assert_nan_prefix(rsi, 3)
    assert rsi.iloc[3] == pytest.approx(75.0)
    assert rsi.iloc[4] == pytest.approx(85.7142857143)
    assert rsi.iloc[5] == pytest.approx(64.8648648649)
    assert rsi.iloc[6] == pytest.approx(79.6875)


def test_calculate_rsi_handles_flat_rising_and_falling_paths() -> None:
    flat = calculate_rsi(pd.Series([5, 5, 5, 5, 5], dtype="float64"), window=3)
    rising = calculate_rsi(pd.Series([1, 2, 3, 4, 5], dtype="float64"), window=3)
    falling = calculate_rsi(pd.Series([5, 4, 3, 2, 1], dtype="float64"), window=3)

    assert_nan_prefix(flat, 3)
    assert flat.iloc[3:].tolist() == [50.0, 50.0]
    assert rising.iloc[3:].tolist() == [100.0, 100.0]
    assert falling.iloc[3:].tolist() == [0.0, 0.0]


def test_calculate_rsi_restarts_warmup_after_missing_values() -> None:
    close = pd.Series([10, 11, 12, 13, math.nan, 14, 15, 16, 17], dtype="float64")

    rsi = calculate_rsi(close, window=3)

    assert rsi.iloc[3] == 100.0
    assert rsi.iloc[4:8].isna().all()
    assert rsi.iloc[8] == 100.0


def test_add_rsi_slope_features_does_not_mutate_input() -> None:
    df = pd.DataFrame({"rsi_14": [40.0, 42.0, 45.0, 43.0, 46.0]})
    original = df.copy(deep=True)

    result = add_rsi_slope_features(df, periods=(1, 3))

    pd.testing.assert_frame_equal(df, original)
    assert "rsi_slope_1" not in df.columns
    assert pd.isna(result["rsi_slope_1"].iloc[0])
    assert result["rsi_slope_1"].iloc[1:].tolist() == [2.0, 3.0, -2.0, 3.0]
    assert result["rsi_slope_3"].iloc[:3].isna().all()
    assert result["rsi_slope_3"].iloc[3:].tolist() == [3.0, 4.0]


def test_add_rsi_ema_features_and_spreads_do_not_mutate_input() -> None:
    df = pd.DataFrame({"rsi_14": [40.0, 50.0, 60.0, 55.0]})
    original = df.copy(deep=True)

    result = add_rsi_ema_features(df, spans=(2, 3), spreads=((2, 3),))

    pd.testing.assert_frame_equal(df, original)
    assert "rsi_ema_2" not in df.columns
    expected_ema_2 = df["rsi_14"].ewm(span=2, adjust=False).mean()
    expected_ema_3 = df["rsi_14"].ewm(span=3, adjust=False).mean()
    pd.testing.assert_series_equal(result["rsi_ema_2"], expected_ema_2, check_names=False)
    pd.testing.assert_series_equal(result["rsi_ema_3"], expected_ema_3, check_names=False)
    pd.testing.assert_series_equal(
        result["rsi_ema_2_minus_3"],
        expected_ema_2 - expected_ema_3,
        check_names=False,
    )


def test_add_rsi_recency_features_builds_expected_columns_without_mutation() -> None:
    df = pd.DataFrame({"closeadj": [10, 11, 13, 12, 14, 13, 15]}, dtype="float64")
    original = df.copy(deep=True)

    result = add_rsi_recency_features(
        df,
        rsi_window=3,
        slope_periods=(1,),
        ema_spans=(2, 3),
        ema_spreads=((2, 3),),
    )

    pd.testing.assert_frame_equal(df, original)
    expected_columns = {
        "closeadj",
        "rsi_3",
        "rsi_slope_1",
        "rsi_ema_2",
        "rsi_ema_3",
        "rsi_ema_2_minus_3",
    }
    assert set(result.columns) == expected_columns
    assert result["rsi_3"].iloc[3] == pytest.approx(75.0)
    assert result["rsi_slope_1"].iloc[4] == pytest.approx(
        result["rsi_3"].iloc[4] - result["rsi_3"].iloc[3]
    )
