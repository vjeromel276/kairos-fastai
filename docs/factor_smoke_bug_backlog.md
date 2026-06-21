# Factor Smoke Bug Backlog

This backlog tracks blockers found during the large-cap factor smoke run. These
items should be handled one at a time with the same process used for the smoke
backlog: implement, test, commit, push, repeat.

## Goal

Make the intended factor buckets testable before promoting to
`universe_fastai_v1` or adding more model complexity.

The current smoke decision is `watch`, not `keep`, because several intended
independent buckets were not actually evaluated under the current complete-case
policy, and sector neutrality could not be checked.

## Working Rules

- Work one bug at a time.
- Keep fixes on `rsi-experiments` unless a new branch is explicitly requested.
- Commit and push each completed bug after its test plan passes.
- Keep generated DuckDB tables, JSON reports, CSVs, and model artifacts out of
  Git.
- Prefer a small fixture test for each bug before rerunning the large-cap smoke
  commands.

## Bug Backlog

### FSB-001: Full-Bucket Complete-Case Policy Makes Sparse Features Mandatory

Status: Done

Severity: High

Problem:
The bucket model, ablation, and walk-forward paths currently treat every feature
column in a bucket as mandatory. One all-null or sparse optional feature can
drop all rows and prevent the whole bucket from being evaluated.

Evidence:
- `volume_liquidity`, `fundamental_quality`, and `valuation` skipped every
  walk-forward fold.
- `volume_liquidity` had zero complete rows because `liq_turnover` is all-null.
- `fundamental_quality` and `valuation` had no complete training rows under the
  current split.

Acceptance criteria:
- Bucket evaluation supports a reviewed required/optional feature policy.
- Optional sparse features do not suppress otherwise testable bucket features.
- Skipped features are reported separately from skipped buckets.
- Existing skipped-bucket reporting remains intact when required features are
  unavailable.

Test plan:
- `python -m compileall scripts`
- Add focused tests for required/optional feature handling in bucket-only,
  cumulative ablation, and walk-forward paths.
- Re-run the large-cap bucket-only, cumulative ablation, and walk-forward smoke
  commands.
- `git diff --check`

Suggested commit:
- `add factor bucket feature availability policy`

Evidence:
- Added `docs/factor_smoke_bug_fsb_001.md`.
- Added a reviewed required/optional feature policy to the bucket evaluation
  path.
- Marked `liq_turnover` optional for `volume_liquidity` and `val_fcf_yield`
  optional for `valuation`.
- Updated bucket-only, cumulative ablation, and walk-forward paths to report
  skipped optional features separately from skipped buckets.
- Confirmed `volume_liquidity` and `valuation` now compute in fixed-split and
  walk-forward smoke runs while `fundamental_quality` still skips because its
  required features have no complete training rows.

Validation result:
- `python -m compileall scripts` passed.
- `python -m pytest tests/test_bucket_model_harness.py tests/test_bucket_ablation_harness.py tests/test_walk_forward_factor_driver.py` passed.
- `python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5` passed with output captured at `local_artifacts/factor_smoke_v1/fsb001_bucket_only_report.json`.
- `python scripts/experiments/bucket_ablation_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --bucket-order price cross_sectional volume volatility fundamental valuation regime --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5` passed with output captured at `local_artifacts/factor_smoke_v1/fsb001_cumulative_ablation_report.json`.
- `python scripts/experiments/walk_forward_factor_driver.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-size 756 --validation-size 252 --test-size 252 --step-size 252 --embargo 21 --top-k 5` passed with output captured at `local_artifacts/factor_smoke_v1/fsb001_walk_forward_report.json`.
- `python -m pytest tests` passed.
- `git diff --check` passed.

### FSB-002: Volume Bucket Is Blocked By All-Null `liq_turnover`

Status: Done

Severity: High

Problem:
`liq_turnover` is all-null in `factor_panel_large_cap_smoke_v1`, which causes
the complete-case volume/liquidity bucket to have zero train, validation, and
test rows.

Evidence:
- `docs/factor_smoke_redundancy_diagnostics.md` records `liq_turnover` as
  all-null.
- `docs/factor_smoke_bucket_only_results.md` records `volume_liquidity` skipped
  with `train split has no complete rows`.
- `docs/factor_smoke_walk_forward_evaluation.md` records `volume_liquidity`
  skipped in all 24 folds.

Acceptance criteria:
- Either `liq_turnover` is populated from a valid shares/market-cap source or
  it is excluded from the required volume/liquidity feature set.
- The volume/liquidity bucket can run at least one complete training split on
  the large-cap smoke panel.
- The quality gate records whether turnover is computed, optional, or skipped.

Test plan:
- `python -m compileall scripts`
- Add or update focused volume/liquidity feature tests.
- Rebuild `factor_panel_large_cap_smoke_v1`.
- Run `python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1`.
- Run bucket-only diagnostics for `volume`.
- `git diff --check`

Suggested commit:
- `fix volume turnover feature availability`

Evidence:
- Added `scripts/experiments/factor_feature_policy.py` so the model harness and
  quality gate share the reviewed optional feature policy.
- Added `docs/factor_smoke_bug_fsb_002.md`.
- Updated the quality gate to report optional feature availability.
- Confirmed `liq_turnover` is recorded as optional and skipped because it is
  all-null in `factor_panel_large_cap_smoke_v1`.
- Confirmed the volume/liquidity bucket computes using the remaining 10
  required liquidity features.

Validation result:
- `python -m compileall scripts` passed.
- `python -m pytest tests/test_factor_dataset_quality.py tests/test_bucket_model_harness.py tests/test_bucket_ablation_harness.py tests/test_walk_forward_factor_driver.py` passed.
- `python scripts/experiments/build_factor_panel.py --db data/kairos-fastai.duckdb --panel large_cap_fixed --buckets price volume volatility fundamental valuation regime cross_sectional --output-table factor_panel_large_cap_smoke_v1` passed.
- `python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1` passed with output captured at `local_artifacts/factor_smoke_v1/fsb002_quality_report.txt`.
- `python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets volume --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5` passed with output captured at `local_artifacts/factor_smoke_v1/fsb002_volume_bucket_report.json`.
- `python -m pytest tests` passed.
- `git diff --check` passed.

### FSB-003: Fundamental Quality Bucket Has No Train/Validation Coverage

Status: Done

Severity: High

Problem:
Strict point-in-time fundamental quality features only appear in recent rows in
the smoke panel. Under the current split, the full bucket has no complete train
or validation rows.

Evidence:
- `docs/factor_smoke_bucket_only_results.md` records `fundamental_quality`
  skipped with no complete train rows.
- `docs/factor_smoke_cumulative_ablations.md` records no train or validation
  complete rows and 2,848 complete test rows.
- `docs/factor_smoke_walk_forward_evaluation.md` records
  `fundamental_quality` skipped in all 24 folds.

Acceptance criteria:
- The fundamental quality bucket has an explicit coverage policy.
- Sparse strict-PIT features are either made available across the training
  window, split into a separate recent-only experiment, or marked optional.
- The quality gate reports fundamental feature coverage by split.

Test plan:
- `python -m compileall scripts`
- Add focused tests for fundamental quality coverage/reporting behavior.
- Rebuild or re-check the smoke panel.
- Run bucket-only diagnostics for `fundamental`.
- `git diff --check`

Suggested commit:
- `fix fundamental quality smoke coverage`

Evidence:
- Added `docs/factor_smoke_bug_fsb_003.md`.
- Updated the quality gate to report bucket coverage by chronological split
  when split boundaries are provided.
- Confirmed the original smoke split has zero complete fundamental quality rows
  in train and validation.
- Preserved the strict PIT policy instead of backfilling fundamentals into
  dates where they are not available.
- Ran a separate recent-only fundamental diagnostic where strict-PIT features
  are available.

Validation result:
- `python -m compileall scripts` passed.
- `python -m pytest tests/test_factor_dataset_quality.py` passed.
- `python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21` passed with output captured at `local_artifacts/factor_smoke_v1/fsb003_split_quality_report.txt`.
- `python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets fundamental --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5` passed with skipped-bucket output captured at `local_artifacts/factor_smoke_v1/fsb003_fundamental_standard_report.json`.
- `python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets fundamental --train-start 2025-08-27 --train-end 2025-12-31 --validation-start 2026-02-02 --validation-end 2026-03-31 --test-start 2026-05-01 --test-end 2026-05-19 --embargo 21 --top-k 5` passed with computed recent-only output captured at `local_artifacts/factor_smoke_v1/fsb003_fundamental_recent_report.json`.
- `python -m pytest tests` passed.
- `git diff --check` passed.

### FSB-004: Valuation Bucket Is Blocked By Sparse `val_fcf_yield`

Status: Open

Severity: High

Problem:
`val_fcf_yield` is sparse enough that the full valuation bucket has no complete
train or validation rows under the current split.

Evidence:
- `docs/factor_smoke_quality_gate.md` records sparse `val_fcf_yield`.
- `docs/factor_smoke_bucket_only_results.md` records `valuation` skipped with
  no complete train rows.
- `docs/factor_smoke_cumulative_ablations.md` records no train or validation
  complete rows and 2,791 complete test rows.
- `docs/factor_smoke_walk_forward_evaluation.md` records `valuation` skipped in
  all 24 folds.

Acceptance criteria:
- The valuation bucket has an explicit required/optional feature policy.
- Sparse cash-flow yield does not block other valuation ratios unless it is
  intentionally required for a specific experiment.
- Bucket diagnostics show which valuation features were used and which were
  skipped.

Test plan:
- `python -m compileall scripts`
- Add focused valuation coverage or feature-selection tests.
- Rebuild or re-check the smoke panel.
- Run bucket-only diagnostics for `valuation`.
- `git diff --check`

Suggested commit:
- `fix valuation bucket sparse feature handling`

### FSB-005: Sector Context Is Missing From Score Diagnostics

Status: Open

Severity: Medium

Problem:
`factor_smoke_scores_v1` does not include `sector`, so sector-neutral ranking,
sector breakdown, and top-K sector concentration diagnostics are skipped.

Evidence:
- `docs/factor_smoke_neutrality_diagnostics.md` records sector diagnostics as
  skipped because `sector` is missing.
- The scoreboard decision remains `watch` partly because sector concentration
  cannot be assessed.

Acceptance criteria:
- If sector or industry data exists in local source tables, it is carried into
  the factor panel or score export.
- If no sector source is available, the missing source is documented and the
  diagnostics retain an explicit skip.
- Neutrality diagnostics can compute sector metrics for the smoke score table
  when sector data is available.

Test plan:
- `python -m compileall scripts`
- Add focused tests for carrying optional sector data into score exports or for
  explicit missing-source reporting.
- Re-export `factor_smoke_scores_v1`.
- Run `python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --beta-column risk_beta_spy_21d --top-k 5`.
- `git diff --check`

Suggested commit:
- `add sector context to factor smoke scores`

### FSB-006: Validation/Test Score Summaries Are Not Split In Diagnostics Notes

Status: Open

Severity: Medium

Problem:
The score export contains a `split` column, but neutrality and turnover notes
summarize the combined validation/test scored table. That is useful for smoke
plumbing, but it can blur validation and test behavior in decision notes.

Evidence:
- `docs/factor_smoke_score_export.md` notes that later promotion work should
  separate validation, test, and walk-forward summaries.
- `factor_smoke_scores_v1` includes both validation and test rows.

Acceptance criteria:
- Diagnostics can be run or summarized by `split`.
- Decision notes distinguish validation and test behavior when using
  `factor_smoke_scores_v1`.
- Combined-table metrics remain available as a convenience summary.

Test plan:
- `python -m compileall scripts`
- Add focused tests for split-filtered diagnostics or split-grouped summaries.
- Re-run neutrality and turnover diagnostics for validation and test splits.
- `git diff --check`

Suggested commit:
- `add split-aware factor score diagnostics`

## Recommended Fix Order

1. `FSB-001`: establish required/optional feature policy first.
2. `FSB-002`: unblock the volume/liquidity bucket.
3. `FSB-004`: unblock valuation sparse-feature handling.
4. `FSB-003`: decide the fundamental quality coverage policy.
5. `FSB-005`: add sector context or document the missing source.
6. `FSB-006`: make diagnostics split-aware before promotion decisions.
