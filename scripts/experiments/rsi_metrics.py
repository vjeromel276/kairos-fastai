"""Metrics and naive baselines for RSI experiments."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def numeric_series(values: Iterable[object] | pd.Series, name: str) -> pd.Series:
    if isinstance(values, pd.Series):
        series = values.copy()
    else:
        series = pd.Series(values)
    return pd.to_numeric(series, errors="coerce").rename(name)


def aligned_numeric_pairs(
    actual: Iterable[object] | pd.Series,
    predicted: Iterable[object] | pd.Series,
) -> pd.DataFrame:
    pairs = pd.concat(
        [
            numeric_series(actual, "actual"),
            numeric_series(predicted, "predicted"),
        ],
        axis=1,
    )
    pairs = pairs.replace([np.inf, -np.inf], np.nan)
    return pairs.dropna(subset=["actual", "predicted"])


def regression_metrics(
    actual: Iterable[object] | pd.Series,
    predicted: Iterable[object] | pd.Series,
) -> dict[str, float | int]:
    """Return null-safe regression metrics."""
    pairs = aligned_numeric_pairs(actual, predicted)
    count = len(pairs)
    if count == 0:
        return {
            "count": 0,
            "mae": np.nan,
            "rmse": np.nan,
            "correlation": np.nan,
            "information_coefficient": np.nan,
        }

    errors = pairs["predicted"] - pairs["actual"]
    if count < 2 or pairs["predicted"].nunique() < 2 or pairs["actual"].nunique() < 2:
        correlation = np.nan
        information_coefficient = np.nan
    else:
        correlation = float(pairs["predicted"].corr(pairs["actual"], method="pearson"))
        information_coefficient = float(
            pairs["predicted"].corr(pairs["actual"], method="spearman")
        )

    return {
        "count": count,
        "mae": float(errors.abs().mean()),
        "rmse": float(np.sqrt((errors**2).mean())),
        "correlation": correlation,
        "information_coefficient": information_coefficient,
    }


def classification_metrics(
    actual: Iterable[object] | pd.Series,
    predicted_score: Iterable[object] | pd.Series,
    threshold: float = 0.5,
) -> dict[str, float | int]:
    """Return null-safe binary classification metrics."""
    pairs = aligned_numeric_pairs(actual, predicted_score)
    count = len(pairs)
    if count == 0:
        return {
            "count": 0,
            "directional_accuracy": np.nan,
            "precision": np.nan,
            "recall": np.nan,
            "auc": np.nan,
        }

    actual_label = (pairs["actual"] > 0).astype("int64")
    predicted_label = (pairs["predicted"] >= threshold).astype("int64")

    true_positive = int(((predicted_label == 1) & (actual_label == 1)).sum())
    false_positive = int(((predicted_label == 1) & (actual_label == 0)).sum())
    false_negative = int(((predicted_label == 0) & (actual_label == 1)).sum())

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0

    if actual_label.nunique() < 2:
        auc = np.nan
    else:
        auc = float(roc_auc_score(actual_label, pairs["predicted"]))

    return {
        "count": count,
        "directional_accuracy": float((predicted_label == actual_label).mean()),
        "precision": float(precision),
        "recall": float(recall),
        "auc": auc,
    }


def mean_return_baseline(
    train_returns: Iterable[object] | pd.Series,
    prediction_index: pd.Index,
) -> pd.Series:
    """Predict the mean non-null training return for every requested row."""
    train = numeric_series(train_returns, "train_returns")
    mean_return = train.dropna().mean()
    return pd.Series(mean_return, index=prediction_index, dtype="float64")


def always_up_baseline(prediction_index: pd.Index) -> pd.Series:
    """Predict positive direction for every requested row."""
    return pd.Series(1.0, index=prediction_index, dtype="float64")


def prior_return_baseline(
    close: Iterable[object] | pd.Series,
    horizon_days: int = 5,
) -> pd.Series:
    """Use the previous `horizon_days` return as a no-future-information baseline."""
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    close_series = numeric_series(close, "close")
    return close_series / close_series.shift(horizon_days) - 1.0
