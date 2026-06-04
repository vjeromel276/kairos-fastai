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

Status: Fixed

Problem: API URLs are built with `api_key=` in the query string. Logged exceptions from `requests` can include the full URL, exposing secrets in logs or console output.

Fix plan: Use `requests.get(..., params=...)` and add a small redaction helper for any URL or exception text before logging. Keep `.env` ignored.

Implementation notes: Implemented on 2026-05-31. Pipeline API requests now pass the Nasdaq key through `requests.get(..., params=...)` instead of appending `api_key=` to constructed URLs. Added a redaction helper in both pipeline entrypoints for URL-style and params-dict-style exception text, and request failure logging now emits redacted messages without printing raw tracebacks that could repeat secret-bearing exception strings. `.gitignore` already ignored `.env`.

Files changed:
- `scripts/pipeline/sharadar_data_sync.py`
- `scripts/pipeline/full_sharadar_refresh.py`
- `tests/test_api_key_redaction.py`
- `tests/test_incremental_overlap.py`
- `tests/test_pagination_safety.py`

Test plan: Unit test the redaction helper with URLs containing `api_key=secret`. Force a mocked request failure and verify logs do not contain the raw key.

Evidence: Added focused redaction tests for both pipeline entrypoints. The tests verify URL and params-dict API key redaction, then force mocked request failures whose exception text contains the raw key in both forms and assert captured logs contain `<redacted>` without the secret. Existing request-mocking tests were updated to assert API filters are passed through `params`.

Validation command:
- `python -m compileall scripts`
- `conda run -n kairos-gpu python -m pytest tests/test_api_key_redaction.py`
- `conda run -n kairos-gpu python -m pytest tests`
- `git diff --check`

Validation result: Passed. `compileall` completed successfully; the focused API-key redaction tests reported `4 passed`; the full test suite reported `10 passed`; `git diff --check` produced no whitespace errors.

## AIT-004: Full-Reload Tables Can Miss Deletions Or Corrections

Status: Fixed

Problem: Full-reload tables are still skipped when the incremental staleness check finds no newer date. This can miss deletions or snapshot corrections in tables such as `TICKERS` unless `--force` is used manually.

Fix plan: For `reload_mode = "full"`, reload on the normal full-refresh path or add a separate freshness policy that does not rely only on max date.

Implementation notes: Implemented on 2026-05-31. `full_sharadar_refresh.py` now treats `reload_mode = "full"` tables as full-reload work whenever they are selected, instead of gating them on an incremental max-date API check. Date-bearing full-reload tables still report the local max date for visibility, and no-date reference tables keep the existing full-reload behavior.

Files changed:
- `scripts/pipeline/full_sharadar_refresh.py`
- `tests/test_full_reload_policy.py`

Test plan: Mock a full table with the same max date but changed/deleted rows. Verify the refresh replaces local contents without requiring `--force`.

Evidence: Added a focused TICKERS regression test that seeds two local rows at the current max date, mocks a replacement download with the same max date containing one corrected row, runs `refresh_table()` without `--force`, and verifies the local table is replaced so the deleted row is removed and the corrected row remains.

Validation command:
- `python -m compileall scripts`
- `conda run -n kairos-gpu python -m pytest tests/test_full_reload_policy.py`
- `conda run -n kairos-gpu python -m pytest tests`
- `git diff --check`

Validation result: Passed. `compileall` completed successfully; the focused full-reload policy test reported `1 passed`; the full test suite reported `6 passed`; `git diff --check` produced no whitespace errors.

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

## AIT-007: Paginated Downloads Do Not Request 10,000-Row Pages

Status: Fixed

Problem: The download loops stop when a CSV page has fewer than 10,000 rows, but the CSV download requests do not set `qopts.per_page=10000`. If the Nasdaq Data Link API default page size is lower than 10,000, large downloads can still truncate after the first default-sized page because the scripts treat that short page as the final page.

Fix plan: Add `qopts.per_page=10000` to the CSV download params in both pipeline entrypoints. Keep cursor requests using the same page size and add focused tests that assert the download request sends `qopts.per_page=10000`.

Implementation notes: Implemented on 2026-05-31. Both pipeline download functions now include `qopts.per_page=10000` in the base CSV request params, and cursor metadata requests reuse those params so the expected page size stays consistent across paginated calls.

Files changed:
- `scripts/pipeline/sharadar_data_sync.py`
- `scripts/pipeline/full_sharadar_refresh.py`
- `tests/test_pagination_safety.py`

Test plan: Mock CSV and cursor API calls for both `sharadar_data_sync.py` and `full_sharadar_refresh.py`; verify the CSV request params include `qopts.per_page=10000` and pagination behavior still reaches the safety-limit failure path when cursors continue.

Evidence: Tightened the existing mocked pagination-safety helper to assert every CSV and JSON cursor request includes `qopts.per_page=10000`. The existing two-page safety-limit tests still verify both entrypoints fail closed instead of creating or replacing tables with partial data.

Validation command:
- `python -m compileall scripts`
- `conda run -n kairos-gpu python -m pytest tests/test_pagination_safety.py`
- `conda run -n kairos-gpu python -m pytest tests`
- `git diff --check`

Validation result: Passed. `compileall` completed successfully; the focused pagination tests reported `2 passed`; the full test suite reported `10 passed`; `git diff --check` produced no whitespace errors.

## AIT-008: Daily Sync Can Leave `trading_calendar` Stale

Status: Open

Problem: The local audit on 2026-05-31 showed `sep_base` through `2026-05-29` but `trading_calendar` only through `2026-05-22`, missing `2026-05-26` through `2026-05-29`. `full_sharadar_refresh.py` refreshes `trading_calendar`, but `sharadar_data_sync.py` can update `SEP` without refreshing or warning about the calendar.

Fix plan: Rebuild `trading_calendar` after a successful `SEP` update in `sharadar_data_sync.py`, or add a shared calendar refresh helper used by both pipeline entrypoints. Keep check-only mode non-mutating.

Implementation notes: Not implemented.

Test plan: Seed a DuckDB test database with `sep_base` dates newer than `trading_calendar`, mock a successful `SEP` sync, run the daily sync path, and verify `trading_calendar` is rebuilt through the latest `sep_base.date`. Also verify `--check-only` does not mutate the calendar.

Result: Not tested after fix.

## AIT-009: `SFP` Is Refreshable But Not Preserved Or Audited

Status: Open

Problem: `full_sharadar_refresh.py` supports the opt-in `SFP` table as local table `sfp`, but reset tooling does not include `sfp` in the source-table keep/audit lists. If `SFP` is ever refreshed, `prune_to_source_tables.py` will classify it as droppable, and `audit_source_db.py` will not report its state.

Fix plan: Add `sfp` to the reset keep list and audit table lists, with date/entity metadata matching the refresh configuration.

Implementation notes: Not implemented.

Test plan: Run the prune dry-run against a database containing `sfp` and verify it is kept. Run the audit command and verify `sfp` appears with row counts, date range, and distinct ticker count.

Result: Not tested after fix.

## AIT-010: Full Refresh Should Use Bulk Export And Local Ingestion

Status: Fixed

Problem: Full-reload tables can exceed practical cursor-pagination limits and should not be downloaded into one in-memory DataFrame. Large full refreshes need a two-phase flow that downloads the complete source file first, then ingests into DuckDB staging and atomically replaces the target table only after the download and validation succeed.

Fix plan: Route `reload_mode = "full"` tables in `full_sharadar_refresh.py` through Nasdaq Data Link bulk export (`qopts.export=true`). Download the fresh zipped CSV to a per-run local directory, extract the CSV, load it into a temporary DuckDB staging table, atomically replace the production table from staging, and delete downloaded files after successful ingestion. Keep incremental tables on paginated API sync.

Implementation notes: Implemented on 2026-05-31. Added bulk export polling, streamed zip download, safe single-CSV extraction, CSV staging through DuckDB, atomic full-table replacement from staging, success-only cleanup, and CLI controls for download directory, keeping downloads, poll interval, and max poll attempts. Failed full-refresh bulk runs leave downloaded files in place for inspection or manual re-ingestion.

Files changed:
- `scripts/pipeline/full_sharadar_refresh.py`
- `tests/test_bulk_full_refresh.py`
- `tests/test_full_reload_policy.py`

Test plan: Mock a fresh bulk export response with a zipped CSV, verify `full_sharadar_refresh.py` requests `qopts.export=true`, downloads the zip, stages the CSV, atomically replaces `tickers`, and deletes the temporary download directory after success. Verify full-reload scheduling still skips incremental staleness checks and no longer depends on `download_paginated()`.

Evidence: Added a focused bulk full-refresh test that mocks the exporter status response and zip download, ingests a replacement `TICKERS` CSV from disk through DuckDB staging, verifies the table contents are atomically replaced, and confirms downloaded files are removed on success. Updated the full-reload policy test so it asserts full reloads do not call the incremental API check and use the bulk replacement hook.

Validation command:
- `python -m compileall scripts`
- `conda run -n kairos-gpu python -m pytest tests/test_bulk_full_refresh.py tests/test_full_reload_policy.py tests/test_full_replace_atomic.py`
- `conda run -n kairos-gpu python -m pytest tests`
- `conda run -n kairos-gpu python scripts/pipeline/full_sharadar_refresh.py --help`
- `git diff --check`

Validation result: Passed. `compileall` completed successfully; focused full-refresh tests reported `3 passed`; the full test suite reported `11 passed`; help output rendered the new bulk export flags; `git diff --check` produced no whitespace errors.
