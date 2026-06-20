# Factor Smoke Source Readiness

Readiness date: 2026-06-20

Local database: `data/kairos-fastai.duckdb`

This note records the source-data readiness check for the first large-cap
factor smoke experiment.

## Decision

Status: ready for `large_cap_fixed` smoke panel build.

The required smoke sources exist locally and have been refreshed through the
latest available trading date reported by the API for the core price, ratio,
fundamental, and ETF/fund tables used by the smoke run.

## Commands Run

Initial freshness check:

```bash
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --check-only
```

The initial check showed `sep_base`, `daily`, `sf1`, and `sfp` were local
through 2026-06-12 while the API reported 2026-06-18. The smoke run was not
accepted on stale sources.

Refresh commands:

```bash
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --tables SFP
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --tables SF1
```

The default sync updated the standard package tables. `SFP` was refreshed
explicitly because it is opt-in for sync and is required for `SPY`.

Post-refresh checks:

```bash
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --tables SEP DAILY SF1 SFP --check-only
python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb
duckdb data/kairos-fastai.duckdb "SELECT ticker, MIN(date) AS min_date, MAX(date) AS max_date, COUNT(*) AS rows FROM sfp WHERE ticker = 'SPY' GROUP BY ticker"
```

## Required Source State

| source | rows | min_date | max_date | status |
| --- | ---: | --- | --- | --- |
| `sep_base` | 46,743,071 | 1997-01-02 | 2026-06-18 | ready |
| `daily` | 39,826,599 | 1998-12-01 | 2026-06-18 | ready |
| `sf1` | 5,930,341 | 1990-06-06 | 2026-06-18 | ready |
| `sfp` | 15,247,242 | 1997-12-31 | 2026-06-18 | ready |
| `trading_calendar` | 7,412 | 1997-01-02 | 2026-06-18 | ready |

Duplicate key checks:

| table | duplicate `(ticker, date)` keys |
| --- | ---: |
| `sep_base` | 0 |
| `daily` | 0 |

`SPY` proxy evidence from `sfp`:

| ticker | min_date | max_date | rows |
| --- | --- | --- | ---: |
| `SPY` | 1997-12-31 | 2026-06-18 | 7,160 |

## Notes

- The post-refresh `--check-only` command still reports `SF1` as
  `needs_update` even after a same-date overlap refresh. The explicit `SF1`
  sync downloaded the overlap window for 2026-06-18 and added zero rows, so this
  is treated as a non-blocking overlap-check behavior for this smoke run.
- `SFP` is opt-in for normal sync. Future source-readiness runs should either
  include `--tables SFP` or use a command that explicitly refreshes the SPY
  source before beta/regime features are built.
