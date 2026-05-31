# Agent Issue Tracker

Last updated: 2026-05-31

This tracker captures review findings for the project base code. Use each entry to define the problem, implement the fix, record verification steps, and note final results.

## Current Review Baseline

- `python -m compileall scripts`: passed on 2026-05-25.
- `python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb`: passed on 2026-05-25. All 14 expected source tables existed; `sep_base` and `daily` had zero duplicate `(ticker, date)` keys.
- `python scripts/fastai_reset/prune_to_source_tables.py --db data/kairos-fastai.duckdb --dry-run`: passed on 2026-05-25. No extra DB objects were found.

## AIT-001: Paginated Downloads Can Silently Truncate Large Tables

Status: Fixed

Problem: `full_sharadar_refresh.py` stops after `PAGE_SAFETY_LIMIT = 500`, and `sharadar_data_sync.py` stops after 50 pages. If the limit is reached, the scripts log a warning but still return the partial DataFrame as successful. Large tables such as `sep_base`, `daily`, `sf2`, and `sf3` exceed these row counts in a full download.

Fix plan: Treat page-limit exhaustion as a hard failure, or replace all-at-once DataFrame collection with page-by-page staging into a temp table and commit only after the cursor is exhausted.

Implementation notes: Implemented on 2026-05-26. The pagination safety limit now fails the download when the API still returns `next_cursor_id` at the cap, so callers mark the table as `download_failed` before any merge or replacement can run.

Files changed:
- `scripts/pipeline/sharadar_data_sync.py`
- `scripts/pipeline/full_sharadar_refresh.py`
- `tests/test_pagination_safety.py`

Test plan: Mock paginated API responses where `next_cursor_id` remains present at the safety limit. Verify the sync exits non-zero and does not create or replace a source table with partial data.

Evidence: Added focused mocked-pagination tests for both the daily sync and full refresh entrypoints. The tests force a two-page safety limit while the mocked API keeps returning `next_cursor_id`, then verify `main()` returns non-zero and the source table is not created or replaced with partial data.

Validation command:
- `python -m compileall scripts`
- `python -m pytest tests/test_pagination_safety.py`

Validation result: Passed. `compileall` completed successfully; pytest reported `2 passed in 0.55s`.

## AIT-002: Same-Date Incremental Updates Are Dropped

Status: Fixed

Problem: Tables using `date_field.gte` download rows for the local max date, but insertion filters with `WHERE date_field > local_max`. Same-date corrections are skipped, and `--force` still does not reconcile existing max-date rows.

Fix plan: Add table-specific natural keys and perform an upsert, or delete and reload a bounded overlap window such as `local_max - N days` through the latest API date inside a transaction.

Implementation notes: Implemented on 2026-05-31. Incremental `use_gte` tables now treat the local max date as an overlap window during freshness checks. When existing data is present, the write path deletes rows at or after the local max date and inserts the downloaded replacement rows inside a transaction, so same-date corrections are reconciled instead of filtered out. Non-`use_gte` tables still append rows strictly newer than the local max date.

Files changed:
- `scripts/pipeline/sharadar_data_sync.py`
- `scripts/pipeline/full_sharadar_refresh.py`
- `tests/test_incremental_overlap.py`

Test plan: Seed a DuckDB test table with a max-date row, mock an API response containing a corrected row for that same date, run sync, and verify the stored row changes.

Evidence: Added focused tests for the daily sync and full refresh entrypoints. Each test seeds a max-date row, mocks the API check/download response with a corrected row for that same date, runs the normal non-force sync path, and verifies the stored value is updated without duplicating the row. The tests also assert the API check uses the overlap date rather than `local_max + 1`.

Validation command:
- `python -m compileall scripts`
- `conda run -n kairos-gpu python -m pytest tests/test_incremental_overlap.py`
- `conda run -n kairos-gpu python -m pytest tests`
- `git diff --check`

Validation result: Passed. `compileall` completed successfully; the focused overlap tests reported `2 passed`; the full test suite reported `5 passed`; `git diff --check` produced no whitespace errors.

## AIT-003: API Keys May Leak Through Logged Request Errors

Status: Partially mitigated

Problem: API URLs are built with `api_key=` in the query string. Logged exceptions from `requests` can include the full URL, exposing secrets in logs or console output.

Fix plan: Use `requests.get(..., params=...)` and add a small redaction helper for any URL or exception text before logging. Keep `.env` ignored.

Implementation notes: `.gitignore` now includes `.env`. URL redaction is not implemented.

Test plan: Unit test the redaction helper with URLs containing `api_key=secret`. Force a mocked request failure and verify logs do not contain the raw key.

Result: `.env` ignore verified by inspection; log redaction not tested after fix.

## AIT-004: Full-Reload Tables Can Miss Deletions Or Corrections

Status: Open

Problem: Full-reload tables are still skipped when the incremental staleness check finds no newer date. This can miss deletions or snapshot corrections in tables such as `TICKERS` unless `--force` is used manually.

Fix plan: For `reload_mode = "full"`, reload on the normal full-refresh path or add a separate freshness policy that does not rely only on max date.

Implementation notes: Not implemented.

Test plan: Mock a full table with the same max date but changed/deleted rows. Verify the refresh replaces local contents without requiring `--force`.

Result: Not tested after fix.

## AIT-005: Full Replacement Is Not Atomic

Status: Fixed

Problem: `replace_full()` drops the existing table before creating the replacement. If table creation fails, the database is left without that source table.

Fix plan: Create a replacement temp table first, validate row count/schema, then swap inside a transaction. Keep the old table until the new table is ready.

Implementation notes: Implemented on 2026-05-26. `replace_full()` now creates and validates a temporary replacement table before entering the swap. The old table is dropped and the replacement is created inside a transaction, so failures during the swap roll back to the original table.

Files changed:
- `scripts/pipeline/full_sharadar_refresh.py`
- `tests/test_full_replace_atomic.py`

Test plan: Inject a failure between replacement creation and swap. Verify the original table remains present and unchanged.

Evidence: Added a focused DuckDB test that seeds an existing `tickers` table, injects a failure after the transactional drop and before replacement creation, and verifies the original row remains present afterward.

Validation command:
- `python -m compileall scripts`
- `python -m pytest tests/test_full_replace_atomic.py`

Validation result: Passed. `compileall` completed successfully; pytest reported `1 passed in 0.32s`.

## AIT-006: Help Text Still References `kairos-flow.duckdb`

Status: Fixed

Problem: Some script docstrings and argparse examples still use `data/kairos-flow.duckdb`, which is the original DB name this reset is intended to avoid.

Fix plan: Update script examples to use `data/kairos-fastai.duckdb` consistently.

Implementation notes: Implemented on 2026-05-31. Updated the stale argparse examples and full-refresh module usage examples to reference `data/kairos-fastai.duckdb` consistently. Also corrected the daily sync help examples to use the current `scripts/pipeline/sharadar_data_sync.py` path.

Files changed:
- `scripts/pipeline/sharadar_data_sync.py`
- `scripts/pipeline/full_sharadar_refresh.py`

Test plan: Run `python scripts/pipeline/sharadar_data_sync.py --help` and `python scripts/pipeline/full_sharadar_refresh.py --help`; verify no examples reference `kairos-flow.duckdb`.

Evidence: Both help outputs now show `data/kairos-fastai.duckdb` in their examples. A focused search of the two pipeline entrypoints found no remaining `kairos-flow.duckdb` references.

Validation command:
- `python -m compileall scripts`
- `conda run -n kairos-gpu python scripts/pipeline/sharadar_data_sync.py --help`
- `conda run -n kairos-gpu python scripts/pipeline/full_sharadar_refresh.py --help`
- `rg -n "kairos-flow\\.duckdb" scripts/pipeline/sharadar_data_sync.py scripts/pipeline/full_sharadar_refresh.py`

Validation result: Passed. `compileall` completed successfully; both help commands rendered with `data/kairos-fastai.duckdb`; `rg` found no stale `kairos-flow.duckdb` references in the relevant entrypoints.
