# FSB-003 Fundamental Quality Coverage

Run date: 2026-06-20

## Decision

Status: fixed as a coverage-policy issue.

The strict point-in-time fundamental quality features are not available in the
original long training and validation windows. The fix is not to relax the PIT
policy. The quality gate now reports bucket coverage by split, and fundamental
quality is evaluated only in a separate recent-only diagnostic window where the
features are actually available.

## Commands Run

```bash
python -m compileall scripts
python -m pytest tests/test_factor_dataset_quality.py
python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21
python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets fundamental --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets fundamental --train-start 2025-08-27 --train-end 2025-12-31 --validation-start 2026-02-02 --validation-end 2026-03-31 --test-start 2026-05-01 --test-end 2026-05-19 --embargo 21 --top-k 5
```

Local reports:

```text
local_artifacts/factor_smoke_v1/fsb003_split_quality_report.txt
local_artifacts/factor_smoke_v1/fsb003_fundamental_standard_report.json
local_artifacts/factor_smoke_v1/fsb003_fundamental_recent_report.json
```

## Split Coverage

Original smoke split:

| split | rows | rows_any | rows_all | rows_all_with_primary_target |
| --- | ---: | ---: | ---: | ---: |
| train | 113,156 | 0 | 0 | 0 |
| validation | 9,600 | 0 | 0 | 0 |
| test | 11,779 | 3,188 | 3,188 | 2,848 |

The standard fundamental bucket run correctly remains skipped:

```text
train split has no complete rows
```

## Recent-Only Diagnostic

Recent-only split:

| split | rows | min_date | max_date |
| --- | ---: | --- | --- |
| train | 948 | 2025-08-27 | 2025-12-31 |
| validation | 800 | 2026-02-03 | 2026-03-31 |
| test | 260 | 2026-05-01 | 2026-05-19 |

Recent-only metrics:

| metric | value |
| --- | ---: |
| validation top-K average return | 0.0067 |
| test top-K average return | 0.0154 |
| test mean IC | -0.1353 |

## Readout

- Fundamental quality is not usable in the original long-horizon smoke split.
- The strict-PIT policy is preserved.
- A recent-only diagnostic is now possible and recorded, but it is too short to
  promote the bucket.
- Promotion work needs either longer point-in-time fundamental coverage or a
  separate recent-only experiment design with clear limitations.
