# FSB-004 Valuation Sparse Feature Handling

Run date: 2026-06-20

## Decision

Status: fixed.

`val_fcf_yield` is explicitly optional under the shared feature availability
policy. It does not block the valuation bucket when sparse. The valuation bucket
now computes using the five daily valuation yield features and reports
`val_fcf_yield` as skipped optional.

## Commands Run

```bash
python -m compileall scripts
python -m pytest tests/test_bucket_model_harness.py tests/test_factor_dataset_quality.py
python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1
python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets valuation --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
```

Local reports:

```text
local_artifacts/factor_smoke_v1/fsb004_quality_report.txt
local_artifacts/factor_smoke_v1/fsb004_valuation_bucket_report.json
```

## Quality Gate Result

```text
valuation: columns=6, rows_any=131,759, rows_all=3,135, null_values=150,800
optional val_fcf_yield: status=partial, non_null_rows=3,135, null_rows=132,320, reason=optional feature has missing values
Valid: True
```

## Valuation Bucket Result

Used features:

```text
val_earnings_yield
val_sales_yield
val_book_yield
val_ebit_ev_yield
val_ebitda_ev_yield
```

Skipped optional feature:

```text
val_fcf_yield
```

Metrics:

| metric | value |
| --- | ---: |
| complete train rows | 109,460 |
| validation top-K average return | 0.0089 |
| test top-K average return | 0.0151 |

## Readout

The valuation bucket is now testable in the long smoke split. Cash-flow yield
can still be evaluated later as a separate sparse/PIT feature, but it no longer
suppresses the broader valuation ratio bucket.
