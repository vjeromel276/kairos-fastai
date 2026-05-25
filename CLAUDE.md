# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

kairos-fastai is a quantitative finance data pipeline built on DuckDB and the Nasdaq/Sharadar data API. It manages a local DuckDB database (`data/kairos-fastai.duckdb`) of US equity market data (prices, fundamentals, insider transactions, institutional holdings, corporate actions) and builds derived tables like a tradeable stock universe.

## Environment

- **Python dependencies**: duckdb, pandas, requests (no requirements file — install manually)
- **Required env var**: `NASDAQ_DATA_LINK_API_KEY` — needed by all pipeline scripts that hit the Sharadar API

## Key Commands

```bash
# Daily incremental sync of core tables (SEP, DAILY, SF1, SF2)
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb

# Full refresh of all Sharadar tables (includes METRICS, TICKERS, ACTIONS, EVENTS, SF3*, SP500)
python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb

# Check what's stale without downloading
python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --check-only

# Audit source DB: row counts, date ranges, duplicate key checks
python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb

# Prune DB back to source tables only (drops all derived/feature tables)
python scripts/fastai_reset/prune_to_source_tables.py --db data/kairos-fastai.duckdb

# Build the liquid common-stock universe (run inside DuckDB CLI against the DB)
# .read scripts/tables/sql/build_universe_fastai_v1.sql
```

## Architecture

**Two-tier data sync**: `sharadar_data_sync.py` is the lightweight daily driver (4 core tables). `full_sharadar_refresh.py` is the comprehensive tool (15 tables) with both incremental and full-reload modes. Both paginate through the Nasdaq CSV API and merge DataFrames directly into DuckDB (no intermediate parquet files).

**Source tables** (canonical, never derived): `sep_base`, `daily`, `sf1`, `sf2`, `sf3`, `sf3a`, `sf3b`, `tickers`, `sharadar_actions`, `sharadar_events`, `sharadar_metrics`, `sharadar_sp500`, `sharadar_indicators`, `trading_calendar`. These are the tables preserved by `prune_to_source_tables.py`.

**Derived tables** (built from SQL): `universe_fastai_v1` — the tradeable universe filtered to liquid US common stocks (price >= $5, 20-day ADV >= $1M, 60+ trading days of history). Built via SQL in `scripts/tables/sql/`.

**`trading_calendar`** is rebuilt from distinct `sep_base.date` values after every full refresh (unless `--skip-calendar`).

## Database Conventions

- The database file is `data/kairos-fastai.duckdb` (gitignored).
- This repo was forked/reset from a larger `kairos-flow.duckdb` — the prune script has a safety guard refusing to operate on the original.
- `sep_base` can have duplicate `(ticker, date)` rows from the API; deduplication happens at query time using `QUALIFY ROW_NUMBER()` (see `build_universe_fastai_v1.sql`).
