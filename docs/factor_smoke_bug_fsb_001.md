# FSB-001 Feature Availability Policy

Run date: 2026-06-20

## Decision

Status: fixed.

Bucket evaluation now supports a reviewed required/optional feature policy.
Optional sparse fields no longer suppress an otherwise testable bucket. Required
feature gaps still skip the bucket and remain visible.

Current reviewed optional fields:

| bucket | optional feature | reason |
| --- | --- | --- |
| volume_liquidity | `liq_turnover` | Depends on share-count or market-cap inputs that may be absent in a smoke panel. |
| valuation | `val_fcf_yield` | Documented as optional because it combines daily valuation data with PIT fundamentals. |

## Code Behavior

- Bucket-only diagnostics select required features first.
- Optional features are used only when they are complete across rows that
  already satisfy required features and target availability.
- Optional features with missing values are recorded under
  `skipped_optional_columns`.
- Sparse required features still produce a skipped bucket with complete split
  ranges.
- Cumulative ablations and walk-forward aggregation use the same policy.

## Commands Run

Focused tests:

```bash
python -m compileall scripts
python -m pytest tests/test_bucket_model_harness.py tests/test_bucket_ablation_harness.py tests/test_walk_forward_factor_driver.py
```

Large-cap smoke commands:

```bash
python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
python scripts/experiments/bucket_ablation_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --bucket-order price cross_sectional volume volatility fundamental valuation regime --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
python scripts/experiments/walk_forward_factor_driver.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-size 756 --validation-size 252 --test-size 252 --step-size 252 --embargo 21 --top-k 5
```

Local reports:

```text
local_artifacts/factor_smoke_v1/fsb001_bucket_only_report.json
local_artifacts/factor_smoke_v1/fsb001_cumulative_ablation_report.json
local_artifacts/factor_smoke_v1/fsb001_walk_forward_report.json
```

## Results

Bucket-only fixed split:

| bucket | status | model features | skipped optional | validation top-K avg return | test top-K avg return |
| --- | --- | ---: | --- | ---: | ---: |
| price_behavior | computed | 11 | none | 0.0256 | 0.0230 |
| cross_sectional_context | computed | 6 | none | 0.0227 | 0.0286 |
| volume_liquidity | computed | 10 | `liq_turnover` | 0.0192 | 0.0205 |
| volatility_risk | computed | 15 | none | 0.0167 | 0.0223 |
| fundamental_quality | skipped | 9 | none | n/a | n/a |
| valuation | computed | 5 | `val_fcf_yield` | 0.0089 | 0.0151 |
| regime_context | computed | 10 | none | 0.0037 | 0.0217 |

Cumulative ablation:

| bucket | status | recommendation | skipped optional |
| --- | --- | --- | --- |
| price_behavior | computed | keep | none |
| cross_sectional_context | computed | reject | none |
| volume_liquidity | computed | reject | `liq_turnover` |
| volatility_risk | computed | reject | none |
| fundamental_quality | skipped | reject | none |
| valuation | computed | reject | `val_fcf_yield` |
| regime_context | computed | keep | none |

The accepted stack remains:

```text
price_behavior + regime_context
```

Walk-forward:

| bucket | status counts | non-null test folds | mean test top-K avg return |
| --- | --- | ---: | ---: |
| price_behavior | computed 24 | 24 | 0.0222 |
| volume_liquidity | computed 24 | 24 | 0.0216 |
| volatility_risk | computed 24 | 24 | 0.0185 |
| fundamental_quality | skipped 24 | 0 | n/a |
| valuation | computed 24 | 24 | 0.0189 |
| regime_context | computed 24 | 24 | 0.0183 |
| cross_sectional_context | computed 24 | 24 | 0.0232 |

## Notes

The large-cap runs emitted SciPy `LinAlgWarning` messages for ill-conditioned
ridge solves after additional buckets became computable. The commands completed
successfully, but model conditioning should remain visible in later promotion
work.
