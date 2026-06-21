# Factor Smoke Bucket-Only Results

Run date: 2026-06-20

Panel table:

```text
factor_panel_large_cap_smoke_v1
```

## Decision

Status: pass with one skipped bucket.

After the feature availability fixes, bucket-only diagnostics compute for
price behavior, cross-sectional context, volume/liquidity, volatility/risk,
valuation, and regime context. Fundamental quality still skips in the original
long split because strict point-in-time features have no complete train or
validation rows.

## Command Run

```bash
python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
```

Post-fix report:

```text
local_artifacts/factor_smoke_v1/fsb001_bucket_only_report.json
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

| bucket | model features | skipped optional | validation top-K avg return | validation IC | test top-K avg return | test IC | test top-K win rate |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| price_behavior | 11 | none | 0.0256 | 0.1361 | 0.0230 | 0.0479 | 0.6084 |
| cross_sectional_context | 6 | none | 0.0227 | 0.0713 | 0.0286 | 0.1115 | 0.6122 |
| volume_liquidity | 10 | `liq_turnover` | 0.0192 | 0.0454 | 0.0205 | 0.0214 | 0.5685 |
| volatility_risk | 15 | none | 0.0167 | 0.0693 | 0.0223 | 0.0695 | 0.5983 |
| valuation | 5 | `val_fcf_yield` | 0.0089 | 0.0704 | 0.0151 | -0.0148 | 0.6112 |
| regime_context | 10 | none | 0.0037 | n/a | 0.0217 | n/a | 0.6325 |

Baseline comparison uses `prior_21d_return`.

| bucket | validation top-K return delta | test top-K return delta |
| --- | ---: | ---: |
| price_behavior | 0.0155 | 0.0067 |
| cross_sectional_context | 0.0125 | 0.0123 |
| volume_liquidity | 0.0090 | 0.0042 |
| volatility_risk | 0.0065 | 0.0060 |
| valuation | -0.0012 | -0.0012 |
| regime_context | -0.0065 | 0.0054 |

## Skipped Buckets

| bucket | reason | complete train rows | complete validation rows | complete test rows | review |
| --- | --- | ---: | ---: | ---: | --- |
| fundamental_quality | train split has no complete rows | 0 | 0 | 2,848 | Strict PIT fundamentals only appear in recent rows; do not backfill into earlier dates. |

## Feature Availability Policy

Optional features are no longer mandatory for complete-case bucket modeling.
The current optional features skipped in this run are:

| bucket | skipped optional feature | reason |
| --- | --- | --- |
| volume_liquidity | `liq_turnover` | all-null without a valid share-count or market-cap source in the smoke panel |
| valuation | `val_fcf_yield` | sparse PIT cash-flow feature unavailable in train and validation |

## Readout

- `price_behavior` remains the strongest standalone large-cap smoke bucket by
  validation evidence.
- `cross_sectional_context` has the strongest standalone test top-K return, but
  the cumulative ablation rejected it because it did not improve validation
  versus the prior accepted stack.
- `volume_liquidity` and `valuation` are now testable, but neither earns a
  stack-level keep decision in the current smoke process.
- `fundamental_quality` is still a coverage-policy issue for the long split and
  should stay separate from promotion decisions until longer PIT coverage is
  available.
