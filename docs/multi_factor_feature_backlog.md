# Multi-Factor Feature Backlog

This backlog defines a conservative path from RSI-only experiments toward a
broader, evidence-based equity ranking model. The goal is not to invent exotic
features. The goal is to stand on established empirical asset-pricing work,
build tested feature buckets, and keep only buckets that add out-of-sample
ranking value.

## Reference Anchors

Use these references as the conceptual guardrails:

- Kenneth French Data Library: market, size, value, profitability, investment,
  momentum, reversal, and portfolio-sort data. This is the primary reference
  for known factor families and portfolio-sort thinking.
  <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html>
- Fama/French factor definitions: market, SMB, HML, RMW, and CMA.
  <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_5_factors_2x3.html>
- Gu, Kelly, and Xiu, "Empirical Asset Pricing via Machine Learning": useful
  predictor families include price trend, liquidity, and volatility; nonlinear
  interactions can matter, but overfit control and time-aware validation are
  central.
  <https://academic.oup.com/rfs/article/33/5/2223/5758276>

## Working Rules

- Work one task at a time.
- Do not combine backlog tasks in one commit unless the later task cannot run
  without the earlier task.
- Before starting each task, confirm `git status --short --branch` is clean.
- After each task, run that task's test plan plus `git diff --check`.
- If tests pass, commit with the suggested subject or a similarly specific one.
- Push the branch after each passing commit:

```bash
git push origin rsi-experiments
```

- Keep generated model artifacts, large metrics exports, prediction files, CSVs,
  and DuckDB databases out of Git unless a task explicitly adds a tiny fixture.
- Use time-based validation only. Do not add random train/test splits.
- Use adjusted prices for returns where available.
- Every feature must be known at or before prediction date `T`.
- Prefer panel ranking metrics over one-ticker prediction metrics.
- Treat bucket-specific models as diagnostics. The likely production shape is
  one combined ranking model with ablation evidence.

## Modeling Principles

The feature buckets should be tested as families:

1. Price behavior
2. Cross-sectional context
3. Volume and liquidity
4. Volatility and risk
5. Fundamental quality
6. Valuation
7. Regime context

The research question for each bucket is:

> Does this bucket improve out-of-sample ranking after controlling for the
> buckets already accepted?

Do not promote a bucket because it improves training or validation only. A
bucket earns `keep` only when it improves test-window ranking metrics without
creating unacceptable turnover, missingness, or leakage risk.

## Review Decisions

- Bucket order:

```text
price behavior -> cross-sectional context -> volume/liquidity
-> volatility/risk -> fundamental quality -> valuation -> regime
```

- Horizons:
  - Primary target: 21-trading-day forward adjusted return.
  - Secondary diagnostic target: 5-trading-day forward adjusted return.
- Panels:
  - Use a fixed large-cap panel for build/debug/smoke tests.
  - Use `universe_fastai_v1` for promotion-quality validation.
- Market proxy:
  - Use `SPY` as the first market proxy for beta, market-relative returns, and
    regime features.
- Promotion gate:
  - Use adjusted-price returns.
  - Require turnover, transaction-cost proxy, liquidity/capacity, and
    walk-forward stability checks before a stack earns `keep`.
- RSI:
  - Keep RSI work as tested infrastructure and optional legacy price-behavior
    features.
  - Do not anchor the multi-factor thesis on RSI.

## Backlog

### MFF-001: Add Multi-Factor Backlog And Research Contract

Status: Done

Scope:
- Add this backlog document.
- Define feature buckets, working rules, and review gates.
- No code or model changes.

Acceptance criteria:
- Backlog is reviewable as a standalone plan.
- Tasks are atomic enough to test, commit, and push one at a time.
- The plan explicitly avoids random splits and future leakage.

Test plan:
- Documentation-only check: `git diff --check`

Suggested commit:
- `add multi factor feature backlog`

### MFF-002: Inventory Available Source Tables And Point-In-Time Limits

Status: Draft

Scope:
- Add a read-only inventory note for available DuckDB tables and columns needed
  by the feature buckets.
- Identify which tables are safe for point-in-time features immediately and
  which need lagging or filing-date handling.
- Do not build features yet.

Acceptance criteria:
- Each proposed bucket maps to specific local source tables or is marked blocked.
- Fundamental and valuation data have explicit date semantics before use.
- Missing data risks are documented.

Test plan:
- `python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb`
- `git diff --check`

Suggested commit:
- `document multi factor source inventory`

### MFF-003: Define Factor Dataset Contract

Status: Draft

Scope:
- Add a Markdown or JSON schema contract for the future factor panel table.
- Required keys: `ticker`, `date`.
- Required targets: 21-trading-day and 5-trading-day forward adjusted returns
  and winner labels.
- Required metadata: bucket name, feature names, source table, and maximum
  lookback.

Acceptance criteria:
- Contract defines one row per `(ticker, date)`.
- Contract distinguishes raw source fields from model-ready features.
- Contract defines null handling and target horizon behavior for both primary
  and secondary targets.

Test plan:
- Documentation-only check: `git diff --check`

Suggested commit:
- `define factor dataset contract`

### MFF-004: Add Factor Dataset Quality Checker Skeleton

Status: Draft

Scope:
- Add a read-only checker for future factor panel tables.
- Validate duplicate `(ticker, date)` keys.
- Report row counts, date ranges, feature null rates, target null rates, and
  bucket-level availability.

Acceptance criteria:
- Checker exits non-zero on duplicate keys.
- Checker can run against a temp DuckDB fixture.
- Checker reports enough detail to review bucket health before modeling.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_factor_dataset_quality.py`
- `git diff --check`

Suggested commit:
- `add factor dataset quality checks`

### MFF-005: Add Baseline Panel Target Builder

Status: Draft

Scope:
- Build a small, tested panel target table from adjusted prices.
- Include 21-trading-day primary and 5-trading-day secondary forward return
  horizons.
- Include prior-return baseline fields for comparison.

Acceptance criteria:
- Last `horizon` rows per ticker have null targets for each configured horizon.
- Targets never cross ticker boundaries.
- Tests prove adjusted prices are used where available.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_factor_targets.py`
- `git diff --check`

Suggested commit:
- `add factor panel targets`

### MFF-006: Add Shared Time Split And Embargo Contract For Factor Models

Status: Draft

Scope:
- Reuse or generalize the RSI time split helpers for factor panel experiments.
- Keep train, validation, and test windows global by date.
- Keep embargo trading-day aware.

Acceptance criteria:
- No random splits.
- All tickers share the same date-window boundaries.
- Existing RSI split tests still pass.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_rsi_time_splits.py tests/test_factor_time_splits.py`
- `git diff --check`

Suggested commit:
- `share time splits for factor models`

### MFF-007: Add Factor Scoreboard Template

Status: Draft

Scope:
- Add a tracked scoreboard for bucket and combination results.
- Record bucket set, feature count, model, target, split dates, validation
  metrics, test metrics, turnover proxy, keep/reject decision, and artifact path.

Acceptance criteria:
- Required columns are tested.
- Scoreboard distinguishes bucket-only, cumulative, and final-combined runs.
- No large artifacts are committed.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_factor_scoreboard_schema.py`
- `git diff --check`

Suggested commit:
- `add factor experiment scoreboard`

### MFF-008: Add Price Behavior Feature Bucket

Status: Draft

Scope:
- Build price behavior features from adjusted prices:
  - 1, 5, 21, 63, 126, and 252 trading-day returns
  - distance from 21, 63, and 252-day moving averages
  - recent drawdown from rolling high
  - short-term reversal feature
- Keep RSI features out unless explicitly configured as optional legacy
  price-behavior features.

Acceptance criteria:
- Features use only data through date `T`.
- Warmup/null behavior is deterministic and tested.
- Feature calculations never cross ticker boundaries.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_price_behavior_features.py`
- `git diff --check`

Suggested commit:
- `add price behavior features`

### MFF-009: Add Cross-Sectional Context Feature Bucket

Status: Draft

Scope:
- Add date-level cross-sectional ranks and relative features:
  - market-relative return using `SPY`
  - sector-relative return if sector classification exists
  - percentile ranks for selected price, volume, volatility, and liquidity fields
  - z-scores with winsorization or robust scaling

Acceptance criteria:
- Cross-sectional transforms are fit per date, not across future dates.
- Tests prove ranks do not use later dates.
- Sector-relative features are skipped or marked null if sector data is missing.
- Market-relative features use `SPY` and do not forward-fill unknown future data.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_cross_sectional_features.py`
- `git diff --check`

Suggested commit:
- `add cross sectional context features`

### MFF-010: Add Volume And Liquidity Feature Bucket

Status: Draft

Scope:
- Build volume/liquidity features where source data allows:
  - dollar volume
  - rolling average dollar volume
  - relative volume versus trailing average
  - turnover proxy if shares outstanding or market cap is available
  - liquidity eligibility flags

Acceptance criteria:
- Features degrade gracefully when required fields are missing.
- Dollar-volume features use contemporaneously available price and volume.
- Tests cover null volume and zero price edge cases.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_volume_liquidity_features.py`
- `git diff --check`

Suggested commit:
- `add volume liquidity features`

### MFF-011: Add Volatility And Risk Feature Bucket

Status: Draft

Scope:
- Build volatility/risk features:
  - 21, 63, and 252-day realized volatility
  - downside volatility
  - rolling beta to `SPY`
  - idiosyncratic volatility versus `SPY` if feasible
  - recent max drawdown

Acceptance criteria:
- `SPY` is the documented market proxy.
- Beta calculations use lagged rolling windows only.
- Tests cover constant-price, missing-market, and short-history cases.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_volatility_risk_features.py`
- `git diff --check`

Suggested commit:
- `add volatility risk features`

### MFF-012: Add Fundamental Quality Feature Bucket

Status: Draft

Scope:
- Build fundamental quality features from point-in-time safe fundamentals:
  - gross margin
  - operating margin
  - return on equity/assets if available
  - earnings growth
  - revenue growth
  - debt or leverage measures
- Use filing/report availability dates where available; otherwise require a
  conservative lag before using a reported value.

Acceptance criteria:
- No fundamental value is used before it would have been known.
- Tests include a restatement or late-report fixture if source fields support it.
- Feature builder documents the lag policy.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_fundamental_quality_features.py`
- `git diff --check`

Suggested commit:
- `add fundamental quality features`

### MFF-013: Add Valuation Feature Bucket

Status: Draft

Scope:
- Build valuation features:
  - earnings yield
  - sales yield
  - book-to-market or book yield
  - cash-flow yield where available
  - enterprise-value based ratios only if required inputs are available
- Winsorize or cap extreme ratios in a documented way.

Acceptance criteria:
- Price denominator is aligned to prediction date `T`.
- Fundamental numerator follows the same point-in-time policy as MFF-012.
- Tests cover negative earnings, zero denominators, and missing fundamentals.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_valuation_features.py`
- `git diff --check`

Suggested commit:
- `add valuation features`

### MFF-014: Add Regime Context Feature Bucket

Status: Draft

Scope:
- Build date-level regime features:
  - `SPY` trend state
  - `SPY` drawdown state
  - `SPY` realized volatility state
  - market breadth proxy if available
  - risk-on/risk-off proxy from `SPY` returns and volatility

Acceptance criteria:
- Regime features are date-level and known by date `T`.
- Regime features are joined to all tickers for the same date.
- Tests cover missing `SPY` dates and no future leakage.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_regime_features.py`
- `git diff --check`

Suggested commit:
- `add regime context features`

### MFF-015: Build Bucketed Factor Panel CLI

Status: Draft

Scope:
- Add a CLI that builds a panel table with selected feature buckets.
- Support `--tickers`, `--panel`, `--start-date`, `--end-date`, and `--buckets`.
- Support at least two named panels:
  - fixed large-cap panel for build/debug/smoke tests
  - `universe_fastai_v1` for promotion-quality validation
- Default to a constrained panel; avoid accidental full-universe builds.

Acceptance criteria:
- CLI can build one bucket or multiple buckets.
- Output table has one row per `(ticker, date)`.
- Tests use small temp DuckDB fixtures.
- `universe_fastai_v1` use is explicit, not accidental.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_build_factor_panel.py`
- `git diff --check`

Suggested commit:
- `add bucketed factor panel builder`

### MFF-016: Add Feature Redundancy Diagnostics

Status: Draft

Scope:
- Add read-only diagnostics for feature redundancy:
  - pairwise correlation
  - bucket-level correlation summary
  - missingness overlap
  - simple variance checks
- Do not drop features automatically yet.

Acceptance criteria:
- Diagnostics flag duplicate or near-constant features.
- Diagnostics can run on temp fixtures.
- Output is reviewable before model training.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_feature_redundancy_diagnostics.py`
- `git diff --check`

Suggested commit:
- `add feature redundancy diagnostics`

### MFF-017: Add Bucket-Only Model Harness

Status: Draft

Scope:
- Train diagnostic models using one bucket at a time.
- Start with regularized linear regression/logistic regression or another simple
  model already supported by the repo.
- Evaluate panel ranking metrics by date.

Acceptance criteria:
- Same splits are used for all bucket-only runs.
- Metrics include IC, top-K average return, top-K win rate, and baseline
  comparison.
- No shuffled splits.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_bucket_model_harness.py`
- `git diff --check`

Suggested commit:
- `add bucket only model harness`

### MFF-018: Add Cumulative Bucket Ablation Harness

Status: Draft

Scope:
- Train cumulative models in a fixed order:
  1. price behavior
  2. cross-sectional context
  3. volume/liquidity
  4. volatility/risk
  5. fundamental quality
  6. valuation
  7. regime context
- Report incremental validation and test deltas after each bucket is added.

Acceptance criteria:
- Output identifies whether each bucket improves over the prior accepted stack.
- Test-window degradation is visible, not hidden by validation improvement.
- Tests prove the same rows/splits are used when comparing bucket stacks.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_bucket_ablation_harness.py`
- `git diff --check`

Suggested commit:
- `add cumulative bucket ablations`

### MFF-019: Add Sector-Neutral And Market-Neutral Ranking Diagnostics

Status: Draft

Scope:
- Add diagnostics that measure ranking results:
  - across the full panel
  - within sector, if sector exists
  - after simple market beta or market-relative adjustment, if available

Acceptance criteria:
- Diagnostics show whether results are broad or concentrated in one sector.
- Tests use deterministic sector fixtures.
- If sector data is unavailable, CLI exits with a clear message or skips sector
  diagnostics explicitly.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_factor_neutrality_diagnostics.py`
- `git diff --check`

Suggested commit:
- `add factor neutrality diagnostics`

### MFF-020: Add Turnover And Capacity Proxy Metrics

Status: Draft

Scope:
- Add metrics for:
  - daily top-K turnover
  - average holding overlap
  - liquidity of selected names
  - simple transaction-cost sensitivity using configurable basis points

Acceptance criteria:
- Metrics run on prediction scores and realized returns.
- Tests cover complete turnover, no turnover, and missing score days.
- Scoreboard can record turnover and cost-adjusted return proxies.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_turnover_capacity_metrics.py`
- `git diff --check`

Suggested commit:
- `add turnover capacity metrics`

### MFF-021: Add Walk-Forward Evaluation Driver

Status: Draft

Scope:
- Add a driver for repeated train/validation/test windows.
- Keep windows chronological and non-overlapping where configured.
- Aggregate metrics across folds.

Acceptance criteria:
- Driver records each fold's date range and metrics.
- No fold uses future data for training.
- Tests use a tiny deterministic panel.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_walk_forward_factor_driver.py`
- `git diff --check`

Suggested commit:
- `add walk forward factor evaluation`

### MFF-022: Add Simple Tree-Based Model Option

Status: Draft

Scope:
- Add one controlled nonlinear model option after linear ablations work.
- Prefer a dependency already available in the environment; otherwise use
  scikit-learn tree/forest models before adding new dependencies.
- Keep hyperparameter grid tiny.

Acceptance criteria:
- Model uses the same train/validation/test split contract.
- Hyperparameters are selected only on validation data.
- Tests verify deterministic behavior with a fixed seed.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_factor_tree_models.py`
- `git diff --check`

Suggested commit:
- `add tree based factor model option`

### MFF-023: Add Feature Importance And Stability Report

Status: Draft

Scope:
- Add a report for selected model runs:
  - linear coefficients or permutation importance
  - bucket-level importance
  - fold-to-fold stability
  - top features by bucket

Acceptance criteria:
- Report does not claim causality.
- Importance is calculated only from validation/test-safe fitted models.
- Tests verify output schema.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_factor_importance_report.py`
- `git diff --check`

Suggested commit:
- `add factor importance report`

### MFF-024: Add Final Promotion Gate

Status: Draft

Scope:
- Define the criteria required before a feature stack can be considered a
  candidate model:
  - positive test IC or top-K adjusted-return improvement
  - improvement over baseline after transaction-cost proxy
  - stable across walk-forward folds
  - no obvious leakage or missingness defect
  - acceptable turnover
  - acceptable selected-name liquidity/capacity
- Implement a small checker that reads metrics JSON and exits non-zero if gates
  fail.

Acceptance criteria:
- Gate criteria are explicit and versioned.
- Failed criteria are named in output.
- Tests cover pass and fail cases.

Test plan:
- `python -m compileall scripts`
- `python -m pytest tests/test_factor_promotion_gate.py`
- `git diff --check`

Suggested commit:
- `add factor model promotion gate`

### MFF-025: Record First Full Bucket Stack Decision

Status: Draft

Scope:
- Run the accepted feature stack through the current full evaluation.
- Update the scoreboard with validation/test/walk-forward results.
- Decide whether the stack earns `keep`, `watch`, or `no`.

Acceptance criteria:
- Decision is based on test and walk-forward metrics, not intuition.
- Metrics paths are recorded without committing large artifacts.
- Next task is defined before further model complexity.

Test plan:
- `python -m compileall scripts`
- relevant model/evaluation tests
- `git diff --check`

Suggested commit:
- `record first factor stack decision`

## First Implementation Slice

Start with MFF-001 through MFF-007 before building any new feature bucket. That
creates the reviewable foundation:

```text
research contract -> source inventory -> dataset contract -> quality checks
-> targets -> time splits -> scoreboard
```

Then build buckets in this order:

```text
price behavior -> cross-sectional context -> volume/liquidity
-> volatility/risk -> fundamental quality -> valuation -> regime
```

Only after every bucket has tests should we run bucket-only diagnostics,
cumulative ablations, walk-forward evaluation, and final promotion gates.

## Resolved Review Questions

- Bucket order: use price behavior first, then cross-sectional context, then
  volume/liquidity, volatility/risk, fundamental quality, valuation, and regime.
- Target horizons: build both 21-trading-day and 5-trading-day adjusted forward
  returns; treat 21-day as primary and 5-day as secondary.
- Panels: use both a fixed large-cap panel for build/debug and
  `universe_fastai_v1` for promotion-quality validation.
- Market proxy: use `SPY`.
- Promotion threshold: use adjusted-return performance plus transaction-cost,
  turnover, liquidity/capacity, and walk-forward stability checks.
