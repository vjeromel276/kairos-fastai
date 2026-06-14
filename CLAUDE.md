# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

kairos-fastai is a quantitative finance project with two halves:

1. A **data pipeline** built on DuckDB and the Nasdaq/Sharadar data API. It manages a local DuckDB database (`data/kairos-fastai.duckdb`) of US equity market data (prices, fundamentals, insider transactions, institutional holdings, corporate actions) and builds derived tables like a tradeable stock universe.
2. A **modeling experiment harness** (currently the RSI recency-weighting experiment) that reads from the DuckDB database, builds feature/target datasets, and trains/evaluates time-split baseline models.

## Environment

- **Python dependencies**: duckdb, pandas, requests for the pipeline; scikit-learn (LinearRegression/LogisticRegression) and numpy for experiments. No requirements file — dependencies are installed manually, mostly via the `kairos-gpu` conda env.
- **Required env var**: `NASDAQ_DATA_LINK_API_KEY` — needed by all pipeline scripts that hit the Sharadar API. Experiment scripts read only from the local DB and do not need it.
- **conda env**: tests and scripts are typically run under `conda run -n kairos-gpu python ...`.

## Key Commands

### Pipeline

```bash
# Daily incremental sync of core tables (SEP, DAILY, SF1, SF2)
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb

# Full refresh of all Sharadar tables (includes METRICS, TICKERS, ACTIONS, EVENTS, SF3*, SP500)
python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb

# Check what's stale without downloading
python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --check-only

# Pre-model freshness gate: ensure every model-required source table is current, fail closed if stale
python scripts/pipeline/pre_model_freshness_gate.py --db data/kairos-fastai.duckdb

# Audit source DB: row counts, date ranges, duplicate key checks
python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb

# Prune DB back to source tables only (drops all derived/feature tables); --dry-run to preview
python scripts/fastai_reset/prune_to_source_tables.py --db data/kairos-fastai.duckdb

# Build the liquid common-stock universe (run inside DuckDB CLI against the DB)
# .read scripts/tables/sql/build_universe_fastai_v1.sql
```

### RSI experiments

```bash
# 1. Build a feature+target dataset for one ticker (feature set A=rsi only, B=+slopes, C=+EMA recency)
python scripts/experiments/build_rsi_one_ticker_dataset.py \
  --db data/kairos-fastai.duckdb --ticker AAPL --feature-set A \
  --rsi-window 14 --horizon-days 5

# 2. Validate dataset quality (duplicate keys, null counts, target alignment); exits non-zero if invalid
python scripts/experiments/check_rsi_dataset_quality.py \
  --db data/kairos-fastai.duckdb --table rsi_experiment_one_ticker_v1

# 3. Train + evaluate linear/logistic baselines with time splits and an embargo; --feature-set ALL compares A/B/C
python scripts/experiments/train_rsi_one_ticker_baselines.py \
  --db data/kairos-fastai.duckdb --ticker AAPL --feature-set ALL \
  --train-end 2021-12-31 --validation-end 2022-12-31 --test-end 2023-12-31 \
  --embargo 63 --embargo-unit trading --metrics-json results/aapl_metrics.json
```

### Tests / syntax check

```bash
python -m compileall scripts                          # fast syntax check of all scripts
conda run -n kairos-gpu python -m pytest tests        # full suite
conda run -n kairos-gpu python -m pytest tests/test_rsi_features.py   # one file
```

Tests use temporary in-memory/on-disk DuckDB fixtures and mocked API responses — they never hit the Sharadar API or the real database. (Note: `AGENTS.md` predates the test suite and says no test framework is configured; that is now outdated — `pytest` under `tests/` is the convention.)

## Architecture

### Data pipeline

**Two-tier data sync**: `sharadar_data_sync.py` is the lightweight daily driver (core tables: SEP, DAILY, SF1, SF2). `full_sharadar_refresh.py` is the comprehensive bootstrap/reset tool with both incremental (paginated API) and full-reload (`qopts.export=true` bulk zip → DuckDB staging → atomic swap) modes. Both paginate the Nasdaq CSV API and merge DataFrames directly into DuckDB (no intermediate parquet files). Full refresh is reserved for bootstrap/reset/recovery; routine pre-model staleness is handled by `pre_model_freshness_gate.py`, which updates stale model-required tables through the routine sync path and fails closed if data remains stale beyond a threshold.

**Source tables** (canonical, never derived): `sep_base`, `daily`, `sf1`, `sf2`, `sf3`, `sf3a`, `sf3b`, `sfp`, `tickers`, `sharadar_actions`, `sharadar_events`, `sharadar_metrics`, `sharadar_sp500`, `sharadar_indicators`, `trading_calendar`. These are the tables preserved by `prune_to_source_tables.py` and reported by `audit_source_db.py`.

**Derived tables** (built from SQL): `universe_fastai_v1` — the tradeable universe filtered to liquid US common stocks (price >= $5, 20-day ADV >= $1M, 60+ trading days of history). Built via SQL in `scripts/tables/sql/`.

**`trading_calendar`** is rebuilt from distinct `sep_base.date` values after a full refresh and after any daily sync that advances `SEP` (unless `--skip-calendar` / `--check-only`).

### RSI experiment harness (`scripts/experiments/`)

Pure-Python modules (no DB dependency) hold reusable logic; CLI scripts wire them to DuckDB:

- `rsi_features.py` — Wilder RSI plus slope (`rsi_slope_{p}`), EMA (`rsi_ema_{span}`), and EMA-spread (`rsi_ema_{a}_minus_{b}`) recency features. Pure pandas.
- `rsi_time_splits.py` — non-overlapping train/validation/test windows with an embargo gap (calendar or trading days) to prevent leakage. Default embargo = `max(feature_lookback, prediction_horizon)`.
- `rsi_metrics.py` — null-safe regression (MAE/RMSE/Pearson/Spearman IC) and classification (accuracy/precision/recall/AUC) metrics, plus naive baselines (mean-return, always-up, prior-return).
- `build_rsi_one_ticker_dataset.py` — reads `(ticker, date, closeadj)` from `sep_base`, builds features per feature set (A/B/C), appends forward targets `future_{h}d_return` and `winner_{h}d`, and writes a DuckDB table (single-ticker `rsi_experiment_one_ticker_v1` or panel `rsi_experiment_panel_v1`, `CREATE OR REPLACE`). Panel mode groups by ticker so features never leak across ticker boundaries.
- `check_rsi_dataset_quality.py` — read-only validator (row/ticker counts, date range, duplicate `(ticker,date)`, feature nulls, target alignment).
- `train_rsi_one_ticker_baselines.py` — loads a dataset table, adds prior-return baselines, time-splits with embargo, trains LinearRegression on `future_5d_return` and LogisticRegression on `winner_5d`, and compares model vs baseline metrics; `--feature-set ALL` runs the A/B/C comparison.

**Research question** the harness answers: does RSI recency-weighting (slopes in set B, EMAs in set C) improve out-of-sample 5-day return prediction over RSI-today-alone (set A)? Success = lower validation/test RMSE and higher AUC for B/C vs A.

## Database Conventions

- The database file is `data/kairos-fastai.duckdb` (gitignored). Treat `data/` as local state, not source code.
- This repo was forked/reset from a larger `kairos-flow.duckdb` — the prune script has a safety guard refusing to operate on the original.
- `sep_base` can have duplicate `(ticker, date)` rows from the API; deduplication happens at query time using `QUALIFY ROW_NUMBER()` (see `build_universe_fastai_v1.sql`).
- Experiment feature columns: `rsi_{window}`, `rsi_slope_{period}`, `rsi_ema_{span}`, `rsi_ema_{a}_minus_{b}`. Targets: `future_{h}d_return`, `winner_{h}d`.

## Docs & Workflow

`docs/` holds the contracts and experiment plan; consult before changing behavior:

- `agent_issue_tracker.md` — review findings (AIT-NNN) with problem/fix/evidence/validation. See the tracker-only fix workflow below.
- `project_contracts.md`, `data_contracts.md`, `modeling_rules.md` — invariants (e.g. CLI flags must stay functional; no random splits, use trading-day-aware windows).
- `rsi_experiments.md`, `rsi_experiment_backlog.md` (RSI-NNN tasks), `rsi_experiment_scoreboard.md` — experiment design, roadmap, and result log. Record results in the scoreboard; do not commit large prediction files (reference an ignored local `metrics_path` instead).
- `architecture.md` — high-level feature-pipeline → feature-store → model flow.

**Tracker-only fix workflow** (when asked to fix a tracker item): read `docs/agent_issue_tracker.md` first, pick exactly one Open issue (unless named), inspect only the files needed, make the smallest safe fix, run that item's Test Plan, update its Status/Evidence/Validation Result, and stop after one item. Avoid broad scans, opportunistic refactors, and style-only edits.
