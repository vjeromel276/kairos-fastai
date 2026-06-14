from __future__ import annotations

import math

import pandas as pd
import pytest

from scripts.experiments.rsi_metrics import (
    always_up_baseline,
    classification_metrics,
    mean_return_baseline,
    prior_return_baseline,
    regression_metrics,
)


def test_regression_metrics_filter_null_pairs() -> None:
    actual = pd.Series([1.0, 2.0, None, 4.0])
    predicted = pd.Series([2.0, 1.0, 3.0, None])

    metrics = regression_metrics(actual, predicted)

    assert metrics["count"] == 2
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["rmse"] == pytest.approx(1.0)
    assert metrics["correlation"] == pytest.approx(-1.0)
    assert metrics["information_coefficient"] == pytest.approx(-1.0)


def test_regression_metrics_handle_constant_predictions() -> None:
    metrics = regression_metrics(
        actual=pd.Series([1.0, 2.0, 3.0]),
        predicted=pd.Series([2.0, 2.0, 2.0]),
    )

    assert metrics["count"] == 3
    assert metrics["mae"] == pytest.approx(2.0 / 3.0)
    assert metrics["rmse"] == pytest.approx(math.sqrt(2.0 / 3.0))
    assert math.isnan(metrics["correlation"])
    assert math.isnan(metrics["information_coefficient"])


def test_classification_metrics_handle_constant_predictions() -> None:
    metrics = classification_metrics(
        actual=pd.Series([0, 1, 0, 1]),
        predicted_score=pd.Series([0.5, 0.5, 0.5, 0.5]),
    )

    assert metrics["count"] == 4
    assert metrics["directional_accuracy"] == pytest.approx(0.5)
    assert metrics["precision"] == pytest.approx(0.5)
    assert metrics["recall"] == pytest.approx(1.0)
    assert metrics["auc"] == pytest.approx(0.5)


def test_classification_metrics_handle_all_one_labels_and_nulls() -> None:
    metrics = classification_metrics(
        actual=pd.Series([1, 1, 1, None]),
        predicted_score=pd.Series([0.9, 0.7, None, 0.1]),
    )

    assert metrics["count"] == 2
    assert metrics["directional_accuracy"] == pytest.approx(1.0)
    assert metrics["precision"] == pytest.approx(1.0)
    assert metrics["recall"] == pytest.approx(1.0)
    assert math.isnan(metrics["auc"])


def test_baseline_predictions_are_deterministic() -> None:
    prediction_index = pd.Index([10, 11, 12])

    mean_predictions = mean_return_baseline(
        train_returns=pd.Series([0.01, None, 0.03]),
        prediction_index=prediction_index,
    )
    up_predictions = always_up_baseline(prediction_index)
    prior_predictions = prior_return_baseline(
        pd.Series([100.0, 105.0, 110.0, 100.0]),
        horizon_days=2,
    )

    assert mean_predictions.index.equals(prediction_index)
    assert mean_predictions.tolist() == [0.02, 0.02, 0.02]
    assert up_predictions.tolist() == [1.0, 1.0, 1.0]
    assert prior_predictions.iloc[:2].isna().all()
    assert prior_predictions.iloc[2] == pytest.approx(110.0 / 100.0 - 1.0)
    assert prior_predictions.iloc[3] == pytest.approx(100.0 / 105.0 - 1.0)


def test_empty_metric_inputs_return_nan_metrics() -> None:
    regression = regression_metrics([None], [1.0])
    classification = classification_metrics([None], [1.0])

    assert regression["count"] == 0
    assert classification["count"] == 0
    assert math.isnan(regression["mae"])
    assert math.isnan(classification["directional_accuracy"])
