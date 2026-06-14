# RSI Experiment Backlog

This backlog breaks the RSI recency-weighting experiment into small, testable
steps. Each task should leave the repository in a functioning state.

## Working Rules

- Work one task at a time.
- Do not combine backlog tasks in one commit unless the later task cannot run without the earlier task.
- Before starting each task, confirm `git status --short --branch` is clean.
- After each task, run that task's test plan plus `git diff --check`.
- If tests pass, commit with the suggested subject or a similarly specific one.
- Push the branch after each passing commit:

```bash
git push origin rsi-experiments
```

- Keep generated model artifacts, exported CSVs, and large reports out of Git unless a later task explicitly adds a small tracked fixture.
- Use time-based validation only. Do not add random train/test splits.
- Use adjusted prices for return targets where available. For Sharadar `sep_base`, prefer `closeadj` for RSI and forward returns so splits/dividends do not distort the experiment.

## Current Branch Goal

Answer the core experiment question:

> Does RSI recency weighting improve out-of-sample 5-day return prediction compared to RSI today alone?

The first phase should prove the plumbing on one ticker, then expand to a panel
dataset only after RSI, target alignment, metrics, and time splits are tested.

## Backlog

### RSI-001: Add Tested RSI Feature Helpers

Status: Done

Scope:
- Add a small RSI feature module under `scripts/experiments/`.
- Implement Wilder-style `calculate_rsi(close, window=14)`.
- Implement helpers for slope and RSI EMA features, but keep them pure pandas functions.
- No database reads in this task.

Acceptance criteria:
- RSI output is deterministic for known input.
- Warmup/null behavior is explicit and tested.
- Flat, rising, falling, and mixed price paths are covered.
- Feature helpers do not mutate caller-owned DataFrames.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_features.py`
- `git diff --check`

Suggested commit:
- `add tested rsi feature helpers`

### RSI-002: Build One-Ticker RSI Dataset CLI

Status: Done

Scope:
- Add a CLI that reads `sep_base` from DuckDB for one ticker.
- Build one ticker-date dataset with `closeadj`, `rsi_14`, and RSI-only feature set A.
- Add `future_5d_return = closeadj[T+5] / closeadj[T] - 1`.
- Add `winner_5d = 1 if future_5d_return > 0 else 0`.
- Write to a local DuckDB table, defaulting to `rsi_experiment_one_ticker_v1`.

Acceptance criteria:
- CLI requires `--db` and `--ticker`.
- Output has one row per `ticker,date`.
- Last five rows for each ticker have null `future_5d_return`.
- No future fields are used in features.
- CLI can run against a temporary DuckDB fixture in tests.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_build_rsi_one_ticker_dataset.py`
- `git diff --check`

Suggested commit:
- `add one ticker rsi dataset builder`

### RSI-003: Add Dataset Alignment And Quality Checks

Status: Done

Scope:
- Add a small read-only checker for RSI experiment tables.
- Validate duplicate `(ticker, date)` keys.
- Report row count, date range, null counts by feature, and target availability.
- Validate that `future_5d_return` is null only where the horizon is unavailable.

Acceptance criteria:
- Checker exits non-zero on duplicate keys.
- Checker exits non-zero when target alignment is broken.
- Checker reports enough information to trust the one-ticker dataset before modeling.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_dataset_quality.py`
- `git diff --check`

Suggested commit:
- `add rsi dataset quality checks`

### RSI-004: Add Time Split And Embargo Utilities

Status: Done

Scope:
- Add reusable time-based split helpers for experiment tables.
- Support train, validation, and test date boundaries.
- Add an embargo measured in trading rows or calendar dates, with the default based on `max(feature_lookback, prediction_horizon)`.
- Do not shuffle rows.

Acceptance criteria:
- Train dates are earlier than validation dates.
- Validation dates are earlier than test dates.
- Embargo rows are excluded between split windows.
- Tests prove no overlapping dates across train, validation, and test sets.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_time_splits.py`
- `git diff --check`

Suggested commit:
- `add rsi time split utilities`

### RSI-005: Add Evaluation Metric Helpers And Naive Baselines

Status: Done

Scope:
- Add reusable regression metrics: MAE, RMSE, prediction/actual correlation, and information coefficient.
- Add classification metrics: directional accuracy, precision, recall, and AUC.
- Add simple baselines:
  - predict mean future return
  - always predict up
  - predict by prior 5-day return if available

Acceptance criteria:
- Metrics handle null predictions and null targets safely.
- Baseline outputs are deterministic.
- Tests cover edge cases such as constant predictions and all-one labels.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_metrics.py`
- `git diff --check`

Suggested commit:
- `add rsi experiment metrics`

### RSI-006: Train One-Ticker RSI-Today Baselines

Status: Done

Scope:
- Add a CLI to train model A1 and A2 on one ticker:
  - A1: linear regression on `rsi_14` for `future_5d_return`
  - A2: logistic regression on `rsi_14` for `winner_5d`
- Use only rows with complete features and targets.
- Use the time split utilities from RSI-004.
- Print and optionally write a small JSON metrics summary.

Acceptance criteria:
- CLI runs against a temp DuckDB table in tests.
- Model training uses no shuffled split.
- Predictions are produced only for validation/test windows.
- Metrics include baselines from RSI-005.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_one_ticker_baselines.py`
- `git diff --check`

Suggested commit:
- `add one ticker rsi baseline models`

### RSI-007: Add RSI Slope Feature Set B

Status: Done

Scope:
- Extend the dataset builder to include:
  - `rsi_slope_3`
  - `rsi_slope_5`
  - `rsi_slope_10`
  - `rsi_slope_20`
- Keep feature set A behavior available.

Acceptance criteria:
- Slopes are calculated as `rsi_14[T] - rsi_14[T-N]`.
- Early rows without enough history are null.
- Existing feature set A tests still pass.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_features.py tests/test_build_rsi_one_ticker_dataset.py`
- `git diff --check`

Suggested commit:
- `add rsi slope features`

### RSI-008: Add RSI EMA Recency Feature Set C

Status: Done

Scope:
- Extend the dataset builder to include:
  - `rsi_ema_5`
  - `rsi_ema_10`
  - `rsi_ema_20`
  - `rsi_ema_5_minus_10`
  - `rsi_ema_5_minus_20`
- Keep feature sets A and B behavior available.

Acceptance criteria:
- RSI EMA features are based only on RSI values through date `T`.
- EMA spread columns equal the difference between their component columns.
- Existing feature set A and B tests still pass.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_features.py tests/test_build_rsi_one_ticker_dataset.py`
- `git diff --check`

Suggested commit:
- `add rsi ema recency features`

### RSI-009: Compare One-Ticker Feature Sets A, B, And C

Status: Done

Scope:
- Extend the model CLI to select feature set A, B, or C.
- Run linear and logistic models for each feature set.
- Output comparable metrics in a small tabular summary.

Acceptance criteria:
- Same split dates are used for every feature set.
- Metrics identify whether B or C improves over A on validation data.
- Tests verify feature selection changes model input columns without changing targets.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_feature_set_comparison.py`
- `git diff --check`

Suggested commit:
- `compare one ticker rsi feature sets`

### RSI-010: Expand Dataset Builder To A Ticker Panel

Status: Done

Scope:
- Add panel mode to build RSI features for many tickers.
- Start from `universe_fastai_v1` or a constrained ticker/date filter to avoid accidental full-universe rebuilds during early tests.
- Preserve one row per `(ticker, date)`.
- Keep the one-ticker mode working.

Acceptance criteria:
- CLI supports a small ticker list for controlled runs.
- Grouped feature calculations never cross ticker boundaries.
- Tests prove no target or feature values leak across tickers.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_build_rsi_panel_dataset.py`
- `git diff --check`

Suggested commit:
- `add rsi panel dataset builder`

### RSI-011: Add Panel Model Evaluation

Status: Done

Scope:
- Extend the model CLI to train and evaluate on panel data.
- Keep date-based splits global across all tickers.
- Add ranking metrics:
  - top-K average future return
  - top-K win rate
  - information coefficient by date

Acceptance criteria:
- No ticker/date duplicates are accepted.
- Top-K metrics are calculated by date, then aggregated.
- Tests use a small multi-ticker fixture with deterministic rankings.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_panel_models.py`
- `git diff --check`

Suggested commit:
- `add rsi panel model evaluation`

### RSI-012: Add Experiment Scoreboard Updates

Status: Done

Scope:
- Add a tracked Markdown scoreboard or a small JSON/CSV summary template.
- Record experiment ID, feature set, model, target, split dates, validation metrics, test metrics, and keep/reject decision.
- Do not commit large prediction files.

Acceptance criteria:
- Scoreboard can be updated after each model run.
- Tests or checks verify required columns/fields are present.
- The doc makes it clear which results are from one-ticker experiments versus panel experiments.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_scoreboard_schema.py`
- `git diff --check`

Suggested commit:
- `add rsi experiment scoreboard`

### RSI-013: Add Reproducible Run Script

Status: Done

Scope:
- Add a shell script or Python driver that runs the current best one-ticker experiment from dataset build through model evaluation.
- Keep it parameterized by ticker and date split.
- Use existing CLIs rather than duplicating logic.

Acceptance criteria:
- Script fails fast if any step fails.
- Script prints the output table name and metrics path.
- Script can run against a temp or small fixture path in tests if implemented as Python.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_run_driver.py`
- `git diff --check`

Suggested commit:
- `add reproducible rsi run driver`

### RSI-014: Gate RSI Experiments On Source Freshness

Status: Done

Scope:
- Before running real experiments against `data/kairos-fastai.duckdb`, call or document the pre-model freshness gate.
- Add a CLI flag such as `--skip-freshness-check` only if needed for tests.
- Keep tests using temp DuckDB fixtures without external API calls.

Acceptance criteria:
- Real experiment runs do not silently proceed on stale source data.
- Tests do not require network access.
- Failure messaging names the stale source table.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_freshness_gate_integration.py`
- `git diff --check`

Suggested commit:
- `gate rsi experiments on source freshness`

### RSI-015: Decide Whether To Try Sequence Model

Status: Done

Scope:
- Review results from feature sets A, B, and C.
- Decide whether a 20-day RSI sequence model is justified.
- If justified, create a new backlog section for sequence tensors and a small neural network.

Acceptance criteria:
- Decision is based on validation/test metrics, not intuition.
- If rejected, document why.
- If accepted, define the next atomic task before writing model code.

Test plan:
- Documentation-only check: `git diff --check`

Suggested commit:
- `record rsi sequence model decision`

## First Implementation Slice

Start with RSI-001 through RSI-006 before expanding to panel data. That creates
the minimal working experiment:

```text
one ticker -> RSI today -> leakage-safe target -> time split -> baseline models -> metrics
```

Only after that path is tested should the branch add slope, EMA recency, panel
data, or neural-network sequence models.
