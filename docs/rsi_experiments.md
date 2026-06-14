# RSI Recency Weighting Experiment

## Purpose

This experiment is designed to test whether **recent RSI behavior** has predictive value for future stock price movement.

The core question:

> Does RSI history, especially more recent RSI movement, help predict the direction and magnitude of a stock’s future 5-day return?

This experiment starts deliberately with **RSI-only features** before adding other feature families such as volume, volatility, trend, EMA spreads, or market context.

The goal is not to build the final trading model immediately. The goal is to prove whether RSI contains useful signal and whether recency-weighted RSI improves predictive ability compared to using RSI today alone.

---

## Hypothesis

RSI today by itself may be weak, because the same RSI value can represent very different setups.

Example:

| RSI Today | Prior RSI Path | Possible Meaning       |
| --------: | -------------- | ---------------------- |
|        42 | 75 → 60 → 42 | Momentum breakdown     |
|        42 | 22 → 31 → 42 | Recovery from oversold |
|        42 | 44 → 43 → 42 | Neutral / sideways     |
|        42 | 60 → 50 → 42 | Controlled pullback    |

Therefore, the model may perform better if it can see recent RSI behavior, such as:

* RSI slope
* RSI acceleration
* RSI moving averages
* fast RSI average versus slow RSI average
* recent RSI sequence shape

---

## Prediction Target

For each stock-date row, features are known at date `T`.

The target is the future return over the next 5 trading days.

```python
future_5d_return = close[T+5] / close[T] - 1
```

Direction label:

```python
winner_5d = 1 if future_5d_return > 0 else 0
```

Each row answers:

```text
Given RSI information known at date T,
what happened to price from T to T+5?
```

---

## Important Alignment Rule

For any row ending at date `T`, the model may only see information from:

```text
T, T-1, T-2, ..., prior dates
```

The model must not see:

```text
T+1, T+2, T+3, T+4, T+5
```

Those future dates belong to the target period.

No future leakage is allowed.

---

## Dataset Structure

Initial experiment may be run on one stock first to prove the plumbing.

After that, expand to a panel dataset:

```text
ticker + date + RSI-derived features at T → future 5-day return
```

Example table:

| ticker | date       | rsi_14 | rsi_slope_5 | rsi_ema_5 | rsi_ema_20 | rsi_ema_5_minus_20 | future_5d_return | winner_5d |
| ------ | ---------- | -----: | ----------: | --------: | ---------: | -----------------: | ---------------: | --------: |
| AAPL   | 2020-01-02 |   48.2 |         3.1 |      46.7 |       43.5 |                3.2 |            0.018 |         1 |
| AAPL   | 2020-01-03 |   45.9 |        -1.4 |      46.2 |       43.8 |                2.4 |           -0.006 |         0 |
| MSFT   | 2020-01-02 |   61.4 |         5.8 |      59.1 |       52.7 |                6.4 |            0.011 |         1 |

---

## Feature Set A: RSI Today Only

This is the simplest baseline.

Features:

```text
rsi_14
```

Targets:

```text
future_5d_return
winner_5d
```

Purpose:

> Determine whether RSI today alone has any relationship to future 5-day price movement.

Expected result:

RSI today alone may be weak, but it establishes a baseline.

---

## Feature Set B: RSI Slope Features

Add simple historical movement measurements.

Features:

```text
rsi_14
rsi_slope_3
rsi_slope_5
rsi_slope_10
rsi_slope_20
```

Definitions:

```python
rsi_slope_3 = rsi_14[T] - rsi_14[T-3]
rsi_slope_5 = rsi_14[T] - rsi_14[T-5]
rsi_slope_10 = rsi_14[T] - rsi_14[T-10]
rsi_slope_20 = rsi_14[T] - rsi_14[T-20]
```

Purpose:

> Test whether the direction and speed of RSI movement improves prediction.

Example interpretation:

```text
RSI = 42 with positive 5-day slope may indicate recovery.
RSI = 42 with negative 5-day slope may indicate breakdown.
```

---

## Feature Set C: RSI Recency-Weighted Features

Use exponential moving averages of RSI itself.

Features:

```text
rsi_14
rsi_ema_5
rsi_ema_10
rsi_ema_20
rsi_ema_5_minus_10
rsi_ema_5_minus_20
```

Definitions:

```python
rsi_ema_5 = EMA(rsi_14, span=5)
rsi_ema_10 = EMA(rsi_14, span=10)
rsi_ema_20 = EMA(rsi_14, span=20)

rsi_ema_5_minus_10 = rsi_ema_5 - rsi_ema_10
rsi_ema_5_minus_20 = rsi_ema_5 - rsi_ema_20
```

Purpose:

> Test whether recent RSI behavior matters more than older RSI behavior.

Interpretation:

```text
rsi_ema_5 > rsi_ema_20 means recent RSI is stronger than longer RSI.
rsi_ema_5 < rsi_ema_20 means recent RSI is weaker than longer RSI.
```

This is similar to using EMA spreads, but applied to RSI instead of price.

---

## Feature Set D: RSI Slope + EMA Recency

Combine the slope and recency-weighted RSI feature families.

Columns:

```text
rsi_14
rsi_slope_3
rsi_slope_5
rsi_slope_10
rsi_slope_20
rsi_ema_5
rsi_ema_10
rsi_ema_20
rsi_ema_5_minus_10
rsi_ema_5_minus_20
```

Purpose:

> Test whether RSI slope and RSI EMA recency features are complementary or redundant.

---

## Future Sequence Model: RSI Sequence Window

Instead of engineered columns, provide the model a sequence of RSI values.

Example:

```text
Last 20 days of RSI → future 5-day return
```

A single sample contains:

```text
RSI from T-19 through T
```

Target:

```text
future_5d_return from T to T+5
```

Purpose:

> Test whether a neural network can learn the useful shape of recent RSI history without manually engineered slope or EMA features.

Do not build this until the tabular RSI feature sets show stable panel-level
out-of-sample signal.

---

## Model Progression

Do not start with the most complex model.

Use this order:

### Model 1: Linear Regression

Target:

```text
future_5d_return
```

Purpose:

> Establish simple relationship between RSI features and future return magnitude.

---

### Model 2: Logistic Regression

Target:

```text
winner_5d
```

Purpose:

> Establish simple relationship between RSI features and future direction.

---

### Model 3: Tree-Based Model

Suggested models:

```text
Random Forest
LightGBM
XGBoost
```

Purpose:

> Capture nonlinear relationships between RSI features and future returns.

Examples of possible nonlinear behavior:

```text
RSI 50-65 may be bullish.
RSI > 80 may indicate exhaustion.
RSI < 30 may mean oversold bounce or continued weakness depending on slope.
```

---

### Model 4: Small Neural Network / 1D CNN

Input:

```text
20-day RSI sequence
```

Target:

```text
future_5d_return or winner_5d
```

Purpose:

> Test whether the model can learn RSI sequence shape directly.

This should only be attempted after the tabular RSI experiments are working correctly.

---

## Train / Validation / Test Split

Use time-based splits only.

Do not randomly shuffle rows.

Example:

```text
Train:
2012-01-01 through 2020-12-31

Embargo:
63 trading days

Validation:
2021 after embargo

Test:
2022

Walk-forward tests:
2023
2024
2025
```

The embargo prevents leakage from overlapping windows and target periods.

Recommended embargo rule:

```text
embargo = max(feature_lookback, prediction_horizon)
```

For this experiment:

```text
feature_lookback = 63 trading days
prediction_horizon = 5 trading days
embargo = 63 trading days
```

---

## Evaluation Metrics

Regression metrics:

```text
MAE
RMSE
Correlation between predicted return and actual future return
Information coefficient
```

Classification metrics:

```text
Directional accuracy
Precision
Recall
AUC
```

Trading/ranking metrics:

```text
Average future return of top-ranked predictions
Top-K win rate
Sharpe ratio
Max drawdown
Turnover
```

Important:

> Accuracy alone is not enough. A model can be directionally correct but still lose money if the losers are larger than the winners.

---

## Experiment Scoreboard

Track every feature set and model combination.

| Experiment | Features            | Model               | Target    | Validation Result | Test Result | Keep? |
| ---------- | ------------------- | ------------------- | --------- | ----------------: | ----------: | ----- |
| A1         | RSI today           | Linear Regression   | 5d return |               TBD |         TBD | TBD   |
| A2         | RSI today           | Logistic Regression | direction |               TBD |         TBD | TBD   |
| B1         | RSI slopes          | Linear Regression   | 5d return |               TBD |         TBD | TBD   |
| B2         | RSI slopes          | LightGBM            | direction |               TBD |         TBD | TBD   |
| C1         | RSI EMA features    | Linear Regression   | 5d return |               TBD |         TBD | TBD   |
| C2         | RSI EMA features    | LightGBM            | direction |               TBD |         TBD | TBD   |
| D1         | RSI slopes + EMA    | Linear Regression   | 5d return |               TBD |         TBD | TBD   |
| D2         | RSI slopes + EMA    | Logistic Regression | direction |               TBD |         TBD | TBD   |
| S1         | 20-day RSI sequence | 1D CNN              | 5d return |               TBD |         TBD | TBD   |

---

## Success Criteria

A feature set is considered useful only if it improves out-of-sample performance.

Possible success signals:

```text
Higher prediction/actual correlation
Better top-K average return
Better directional accuracy
Lower RMSE or MAE
More stable results across multiple test years
```

A feature should not be kept just because it sounds useful.

Every feature must earn its seat.

---

## Failure Criteria

A feature set should be rejected or deprioritized if:

```text
It only improves training performance but not validation/test performance.
It works in one year but fails across other years.
It adds complexity without improving ranking or return metrics.
It appears to be caused by leakage.
It performs worse than a simple baseline.
```

---

## Baselines

Compare every experiment against simple baselines:

```text
Always predict average future return.
Always predict price goes up.
Predict using RSI today only.
Predict using previous 5-day return only.
```

The model must beat these baselines out-of-sample to be considered useful.

---

## Initial Recommended Build Order

1. Build one-stock RSI table.
2. Confirm RSI calculation.
3. Confirm `future_5d_return` alignment.
4. Train simple linear regression on `rsi_14`.
5. Train logistic regression on `winner_5d`.
6. Add RSI slope features.
7. Add RSI EMA recency-weighted features.
8. Expand from one stock to many stocks.
9. Add time-based train/validation/test split with embargo.
10. Compare model results.
11. Only then test 20-day RSI sequence with a small neural network.

---

## Python Feature Sketch

```python
import pandas as pd
import numpy as np


def calculate_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


def add_rsi_recency_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()

    g["rsi_14"] = calculate_rsi(g["close"], window=14)

    g["rsi_slope_3"] = g["rsi_14"] - g["rsi_14"].shift(3)
    g["rsi_slope_5"] = g["rsi_14"] - g["rsi_14"].shift(5)
    g["rsi_slope_10"] = g["rsi_14"] - g["rsi_14"].shift(10)
    g["rsi_slope_20"] = g["rsi_14"] - g["rsi_14"].shift(20)

    g["rsi_ema_5"] = g["rsi_14"].ewm(span=5, adjust=False).mean()
    g["rsi_ema_10"] = g["rsi_14"].ewm(span=10, adjust=False).mean()
    g["rsi_ema_20"] = g["rsi_14"].ewm(span=20, adjust=False).mean()

    g["rsi_ema_5_minus_10"] = g["rsi_ema_5"] - g["rsi_ema_10"]
    g["rsi_ema_5_minus_20"] = g["rsi_ema_5"] - g["rsi_ema_20"]

    g["future_5d_return"] = g["close"].shift(-5) / g["close"] - 1
    g["winner_5d"] = (g["future_5d_return"] > 0).astype(int)

    return g
```

For many tickers:

```python
df = (
    df.sort_values(["ticker", "date"])
      .groupby("ticker", group_keys=False)
      .apply(add_rsi_recency_features)
)
```

---

## Final Experiment Question

At the end of this experiment, we want to answer:

> Does RSI recency-weighting improve prediction of future 5-day return compared to RSI today alone?

If yes, RSI recency features can be kept and later combined with other feature families.

If no, RSI may still be useful in combination with other features, but RSI-only recency weighting should not be treated as a strong standalone signal.
