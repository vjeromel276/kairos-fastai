# Factor Smoke Bucket-Only Results

Run date: 2026-06-20

Panel table:

```text
factor_panel_large_cap_smoke_v1
```

## Decision

Status: pass with skipped buckets.

The bucket-only smoke harness now records bucket-level skip reasons instead of
aborting when a bucket has no complete training rows. The first smoke run
produced usable bucket-only diagnostics for price behavior, cross-sectional
context, volatility/risk, and regime context.

## Command Run

```bash
python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
```

Global split ranges:

| split | rows | min_date | max_date |
| --- | ---: | --- | --- |
| train | 113,156 | 1997-12-31 | 2021-12-31 |
| validation | 9,600 | 2022-02-02 | 2023-12-29 |
| test | 11,779 | 2024-02-01 | 2026-06-12 |

Target:

```text
future_21d_return
```

Model:

```text
ridge_regression
```

Top-K:

```text
5
```

## Computed Buckets

| bucket | validation top-K avg return | validation IC | test top-K avg return | test IC | test top-K win rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| price_behavior | 0.0256 | 0.1361 | 0.0230 | 0.0479 | 0.6084 |
| cross_sectional_context | 0.0227 | 0.0713 | 0.0286 | 0.1115 | 0.6122 |
| volatility_risk | 0.0167 | 0.0693 | 0.0223 | 0.0695 | 0.5983 |
| regime_context | 0.0037 | n/a | 0.0217 | n/a | 0.6325 |

Baseline comparison uses `prior_21d_return`.

| bucket | validation top-K return delta | test top-K return delta |
| --- | ---: | ---: |
| price_behavior | 0.0155 | 0.0067 |
| cross_sectional_context | 0.0125 | 0.0123 |
| volatility_risk | 0.0065 | 0.0060 |
| regime_context | -0.0065 | 0.0054 |

## Skipped Buckets

| bucket | reason | complete train rows | review |
| --- | --- | ---: | --- |
| volume_liquidity | train split has no complete rows | 0 | `liq_turnover` is all-null and makes the full bucket complete-case model impossible. |
| fundamental_quality | train split has no complete rows | 0 | strict PIT fundamentals only appear in recent rows; no train/validation complete rows under this split. |
| valuation | train split has no complete rows | 0 | `val_fcf_yield` is sparse and causes full-bucket complete-case loss. |

## Harness Fix

The first smoke command failed because one bucket with no complete train rows
stopped the whole harness. The harness now records skipped buckets with:

- `status: skipped`
- skip reason
- feature columns
- complete split ranges

This keeps the smoke run reviewable while preserving the failure information.

## Follow-Up Candidates

- Add feature selection or per-bucket required-feature policy before treating
  all bucket columns as mandatory.
- Exclude `liq_turnover` until the panel builder supplies valid turnover
  inputs.
- Evaluate strict-PIT fundamentals and `val_fcf_yield` separately from broader
  valuation ratios so sparse fields do not suppress the entire bucket.
- Treat regime-context bucket-only IC as undefined because regime features are
  date-level and often produce identical cross-sectional scores within a date.
