# Repository Guidelines

## Project Structure & Module Organization

This repository is a small DuckDB-based Sharadar data pipeline. Python entrypoints live under `scripts/`, grouped by purpose:

- `scripts/pipeline/`: API sync and refresh drivers.
- `scripts/fastai_reset/`: database audit, prune, and reset helpers.
- `scripts/fastai_reset/sql/`: reset-related SQL utilities.
- `scripts/tables/sql/`: SQL builds for derived tables such as `universe_fastai_v1`.

The local DuckDB file lives at `data/kairos-fastai.duckdb` and is ignored by Git. There is currently no committed `tests/` directory or packaged Python module.

## Build, Test, and Development Commands

- `python -m compileall scripts`: syntax-check all Python scripts.
- `python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb`: inspect source table counts, date ranges, and duplicate keys.
- `python scripts/fastai_reset/prune_to_source_tables.py --db data/kairos-fastai.duckdb --dry-run`: preview derived objects that would be dropped.
- `python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --check-only`: check core Sharadar tables without downloading data.
- `python scripts/pipeline/full_sharadar_refresh.py --db data/kairos-fastai.duckdb --check-only`: check the broader Sharadar refresh set.

Run DuckDB SQL scripts from the DuckDB CLI, for example:

```sql
.read scripts/tables/sql/build_universe_fastai_v1.sql
```

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, type hints where they clarify script interfaces, and standard-library tools before adding new dependencies. Keep scripts executable as standalone CLIs with `argparse`. Use `snake_case` for Python functions, variables, and table helper names. SQL should use descriptive CTE names, explicit output columns for derived tables, and lowercase table names matching existing DuckDB objects.

## Testing Guidelines

No formal test framework is configured yet. For changes today, run `python -m compileall scripts` and the relevant `--check-only`, `--dry-run`, or read-only audit command. If adding tests, prefer `pytest`, place tests under `tests/`, and name files `test_<feature>.py`.

## Commit & Pull Request Guidelines

The history is short and uses concise descriptive commit messages. Prefer imperative, specific subjects such as `add sharadar refresh checks` or `fix universe liquidity filter`. Pull requests should include a brief summary, commands run, database-impact notes, and any required environment variables.

## Security & Configuration Tips

Do not commit API keys, `.env` files, logs, CSV exports, or DuckDB databases. Pipeline scripts require `NASDAQ_DATA_LINK_API_KEY` in the environment. Treat `data/` as local state, not source code.

## Tracker-Only Fix Workflow

When asked to fix tracker items:
- Read only `docs/agent_issue_tracker.md` first.
- Select exactly one Open issue unless the user names one.
- Do not hunt for new issues.
- Do not perform broad refactors.
- Inspect only files needed to understand and fix that tracker item.
- Implement the smallest safe fix.
- Run the tracker item's Test Plan.
- Update the tracker Status, Evidence, and Validation Result.
- Stop after one item.

### Context Discipline

When fixing tracker items:
- Read only:
  - the tracker item
  - directly relevant contracts
  - directly relevant source files
  - directly relevant tests
- Avoid broad repository scans.
- Avoid opportunistic refactors.
- Avoid style-only edits.