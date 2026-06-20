# Factor Smoke Experiment Backlog

This backlog tracks the first end-to-end large-cap smoke experiment for the
multi-factor stack. It is separate from `docs/multi_factor_feature_backlog.md`
so we can run and review the current system without mixing execution tasks with
future feature-building tasks.

## Goal

Run the current factor pipeline on the fixed large-cap panel, inspect the
diagnostics, and record a first evidence-based decision before adding more
model complexity.

The decision at the end should be one of:

- promote the same process to `universe_fastai_v1`
- fix data, scoring, or evaluation gaps found by the smoke run
- continue to MFF-022 with a controlled tree-based model option

## Working Rules

- Work one task at a time.
- Keep this work on `rsi-experiments`.
- Commit and push each completed task after its test plan passes.
- Do not commit DuckDB files, JSON metrics, CSVs, prediction exports, or large
  model artifacts.
- Store local metrics/artifacts as ignored files, preferably under:

```text
local_artifacts/factor_smoke_v1/
```

Files ending in `.json`, `.csv`, `.duckdb`, or `.log` are ignored by the
current `.gitignore`; record only compact summaries and artifact paths in Git.

## Smoke Contract

Default panel:

```text
large_cap_fixed
```

Default output table:

```text
factor_panel_large_cap_smoke_v1
```

Default scored table, once score export exists:

```text
factor_smoke_scores_v1
```

Primary target:

```text
future_21d_return
```

Default bucket order:

```text
price -> cross_sectional -> volume -> volatility -> fundamental -> valuation -> regime
```

For the actual `build_factor_panel.py` CLI, build order should satisfy feature
dependencies. In practice, run cross-sectional features after the buckets they
rank:

```text
price volume volatility fundamental valuation regime cross_sectional
```

## Backlog

### FSM-001: Add Factor Smoke Experiment Backlog

Status: Done

Scope:
- Add this backlog document.
- Define the first end-to-end smoke path.
- Keep it separate from the feature-build backlog.

Acceptance criteria:
- The path is atomic enough to run, test, commit, and push one task at a time.
- The backlog explicitly notes the scored-prediction gap needed for neutrality
  and turnover diagnostics.

Test plan:
- `git diff --check`

Suggested commit:
- `add factor smoke experiment backlog`

Evidence:
- Added `docs/factor_smoke_experiment_backlog.md`.

### FSM-002: Verify Source Freshness And Required Tables

Status: Done

Scope:
- Confirm the local DuckDB has current-enough source data for the smoke run.
- Confirm required source tables exist: `sep_base`, `sfp`, `daily`, `sf1`, and
  `trading_calendar`.
- Confirm `SPY` comes from `sfp`.
- Stop if freshness or table availability is not acceptable.

Acceptance criteria:
- Freshness and table availability are recorded in a short note or scoreboard
  decision notes.
- Any stale or missing source data has a clear stop/fix decision.

Test plan:
- `python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --check-only`
- `python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb`
- `git diff --check`

Suggested commit:
- `record factor smoke source readiness`

Evidence:
- Added `docs/factor_smoke_source_readiness.md`.
- Refreshed stale local Sharadar sources before proceeding.
- Confirmed `sep_base`, `daily`, `sf1`, `sfp`, and `trading_calendar` exist
  locally and are current through 2026-06-18 for the smoke run.
- Confirmed `SPY` is available from `sfp` through 2026-06-18.
- Confirmed zero duplicate `(ticker, date)` keys in `sep_base` and `daily`.

### FSM-003: Build Large-Cap Smoke Factor Panel

Status: Done

Scope:
- Build `factor_panel_large_cap_smoke_v1` from the fixed large-cap panel.
- Include current feature buckets:
  - price behavior
  - volume/liquidity
  - volatility/risk
  - fundamental quality
  - valuation
  - regime context
  - cross-sectional context
- Use adjusted-price targets.

Acceptance criteria:
- Output table exists in local DuckDB.
- Output has one row per `(ticker, date)`.
- Output includes 21-day and 5-day targets plus feature columns from each
  requested bucket.
- No generated table or export file is committed.

Test plan:
- `python scripts/experiments/build_factor_panel.py --db data/kairos-fastai.duckdb --panel large_cap_fixed --buckets price volume volatility fundamental valuation regime cross_sectional --output-table factor_panel_large_cap_smoke_v1`
- `python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1`
- `git diff --check`

Suggested commit:
- `record large cap smoke panel build`

Evidence:
- Added `docs/factor_smoke_panel_build.md`.
- Built `factor_panel_large_cap_smoke_v1` with 135,455 rows for 20 large-cap
  tickers across 1997-12-31 through 2026-06-18.
- Included price, volume, volatility, fundamental, valuation, regime, and
  cross-sectional feature buckets.
- Ran the factor dataset quality checker; result was valid with zero duplicate
  `(ticker, date)` keys.

### FSM-004: Run Factor Panel Quality Gate

Status: Done

Scope:
- Run the dataset quality checker against `factor_panel_large_cap_smoke_v1`.
- Review duplicate keys, required columns, target alignment, bucket
  availability, and null rates.

Acceptance criteria:
- Duplicate `(ticker, date)` count is zero.
- Required target and panel columns are present.
- Bucket null behavior is explainable by warmup windows, source availability,
  or documented point-in-time policy.
- Any blocking quality issue creates a follow-up fix before modeling.

Test plan:
- `python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1`
- `git diff --check`

Suggested commit:
- `record factor smoke quality gate`

Evidence:
- Added `docs/factor_smoke_quality_gate.md`.
- Re-ran the factor dataset quality checker on
  `factor_panel_large_cap_smoke_v1`; result was valid.
- Confirmed zero duplicate keys, valid target/winner alignment, and no blocking
  quality issues.
- Recorded non-blocking warnings for null `liq_turnover`, sparse strict-PIT
  fundamentals, sparse `val_fcf_yield`, and raw carry-through columns.

### FSM-005: Run Feature Redundancy And Missingness Diagnostics

Status: Done

Scope:
- Run redundancy diagnostics on the smoke panel.
- Review high-correlation pairs, near-constant features, bucket-level
  correlation, and missingness overlap.
- Do not drop features automatically in this task.

Acceptance criteria:
- Redundant or low-information feature risks are summarized.
- Any manual feature-removal recommendation is recorded for review before code
  changes.

Test plan:
- `python scripts/experiments/feature_redundancy_diagnostics.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1`
- `git diff --check`

Suggested commit:
- `record factor smoke redundancy diagnostics`

Evidence:
- Added `docs/factor_smoke_redundancy_diagnostics.md`.
- Ran feature redundancy diagnostics on `factor_panel_large_cap_smoke_v1`.
- Recorded `liq_turnover` as all-null, identified 4 high-correlation pairs,
  and documented the largest missingness-overlap risks.
- No features were dropped automatically.

### FSM-006: Run Bucket-Only Smoke Models

Status: Draft

Scope:
- Run bucket-only ridge diagnostics on the smoke panel.
- Use the same chronological date split for every bucket.
- Compare each bucket to the prior-return baseline.

Acceptance criteria:
- Every runnable bucket has validation and test ranking metrics.
- Metrics include top-K average return, top-K win rate, and information
  coefficient.
- Buckets with insufficient complete rows are explicitly recorded.

Test plan:
- `python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5`
- `git diff --check`

Suggested commit:
- `record bucket only smoke results`

### FSM-007: Run Cumulative Bucket Ablations

Status: Draft

Scope:
- Run cumulative bucket ablations in the reviewed bucket order.
- Compare each candidate stack against the prior accepted stack.
- Make validation improvement and test degradation visible.

Acceptance criteria:
- Each bucket receives an initial `keep`, `watch`, or `reject` recommendation.
- Test-window degradation is not hidden by validation improvement.
- Comparison rows and split ranges are recorded.

Test plan:
- `python scripts/experiments/bucket_ablation_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --bucket-order price cross_sectional volume volatility fundamental valuation regime --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5`
- `git diff --check`

Suggested commit:
- `record cumulative smoke ablations`

### FSM-008: Add Or Generate Scored Prediction Table

Status: Draft

Scope:
- Produce a scored panel table for the selected smoke candidate stack.
- This is required before neutrality and turnover/capacity diagnostics can run.
- The table should include at minimum:
  - `ticker`
  - `date`
  - `prediction_score`
  - `future_21d_return`
  - `sector`, if available
  - `risk_beta_spy_21d`, if available
  - `liq_adv_20d`, if available
- If existing harnesses cannot export row-level scores, add the smallest safe
  score-export helper and tests.

Acceptance criteria:
- `factor_smoke_scores_v1` exists locally.
- It has one row per scored `(ticker, date)`.
- It includes enough columns for neutrality and turnover/capacity diagnostics.
- Any new code has focused tests.

Test plan:
- If code is added: `python -m compileall scripts`
- If code is added: run the focused score-export tests
- `python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --top-k 5`
- `python scripts/experiments/turnover_capacity_metrics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --top-k 5`
- `git diff --check`

Suggested commit:
- `add factor smoke score export`

### FSM-009: Run Walk-Forward Smoke Evaluation

Status: Draft

Scope:
- Run repeated chronological folds on the selected bucket stack or candidate
  bucket set.
- Aggregate validation and test ranking metrics across folds.

Acceptance criteria:
- Fold date ranges are recorded.
- No fold uses future data for training.
- Aggregate metrics show whether the signal is stable or isolated to one
  split.

Test plan:
- `python scripts/experiments/walk_forward_factor_driver.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-size 756 --validation-size 252 --test-size 252 --step-size 252 --embargo 21 --top-k 5`
- `git diff --check`

Suggested commit:
- `record walk forward smoke evaluation`

### FSM-010: Run Neutrality Diagnostics

Status: Draft

Scope:
- Run full-panel, sector-neutral, sector-breakdown, and beta-adjusted ranking
  diagnostics on `factor_smoke_scores_v1`.

Acceptance criteria:
- Diagnostics show whether results are broad or concentrated.
- Missing sector or beta data is recorded as an explicit skip, not a silent
  omission.
- If one sector dominates top picks, the decision summary calls that out.

Test plan:
- `python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --beta-column risk_beta_spy_21d --top-k 5`
- `git diff --check`

Suggested commit:
- `record factor smoke neutrality diagnostics`

### FSM-011: Run Turnover And Capacity Diagnostics

Status: Draft

Scope:
- Run turnover, holding-overlap, transaction-cost, and selected-name liquidity
  diagnostics on `factor_smoke_scores_v1`.

Acceptance criteria:
- Daily turnover and average holding overlap are recorded.
- Cost-adjusted top-K return is recorded using configurable basis points.
- Selected-name liquidity/capacity summary is recorded.
- Missing score days are visible.

Test plan:
- `python scripts/experiments/turnover_capacity_metrics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --liquidity-column liq_adv_20d --top-k 5 --cost-bps 10`
- `git diff --check`

Suggested commit:
- `record factor smoke turnover diagnostics`

### FSM-012: Record First Smoke Scoreboard Decision

Status: Draft

Scope:
- Update `docs/factor_experiment_scoreboard.md` with a compact result row or
  rows for the smoke run.
- Record artifact paths for ignored local JSON outputs.
- Make a first `keep`, `watch`, or `reject` decision for the tested stack.

Acceptance criteria:
- Scoreboard includes panel name, ticker set, bucket stack, model, target,
  split windows, validation/test summary, turnover summary, cost-adjusted
  summary, liquidity summary, decision, artifact paths, and commit.
- Decision notes explain the main reason for the decision.
- No large artifacts are committed.

Test plan:
- `python -m pytest tests/test_factor_scoreboard_schema.py`
- `git diff --check`

Suggested commit:
- `record first factor smoke decision`

### FSM-013: Choose Next Path

Status: Draft

Scope:
- Review the smoke decision and choose the next path.

Acceptance criteria:
- One of these paths is selected and documented:
  - promote to `universe_fastai_v1`
  - fix a data/modeling/evaluation blocker found by the smoke run
  - proceed to MFF-022 tree-based model work
- The decision references the smoke evidence, not training-only performance.

Test plan:
- Documentation-only check: `git diff --check`

Suggested commit:
- `record factor smoke next path`
