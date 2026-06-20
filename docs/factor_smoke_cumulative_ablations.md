# Factor Smoke Cumulative Ablations

Run date: 2026-06-20

Panel table:

```text
factor_panel_large_cap_smoke_v1
```

## Decision

Status: pass with rejected sparse buckets.

The cumulative smoke harness now records an explicit `keep`, `watch`, or
`reject` recommendation for every bucket. Candidate stacks that have no
complete training rows are recorded as rejected skipped steps instead of
aborting the run.

Initial accepted smoke stack:

```text
price_behavior + regime_context
```

This is a smoke-run selection only. It is not promotion-quality evidence until
score export, neutrality, turnover/capacity, and walk-forward diagnostics pass.

## Command Run

```bash
python scripts/experiments/bucket_ablation_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --bucket-order price cross_sectional volume volatility fundamental valuation regime --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
```

Global split ranges:

| split | rows | min_date | max_date |
| --- | ---: | --- | --- |
| train | 113,156 | 1997-12-31 | 2021-12-31 |
| validation | 9,600 | 2022-02-02 | 2023-12-29 |
| test | 11,779 | 2024-02-01 | 2026-06-12 |

## Recommendations

| bucket | candidate stack | recommendation | validation top-K avg return | test top-K avg return | validation delta vs prior | test delta vs prior | test degradation visible |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| price_behavior | price_behavior | keep | 0.0256 | 0.0230 | n/a | n/a | false |
| cross_sectional_context | price_behavior + cross_sectional_context | reject | 0.0241 | 0.0240 | -0.0016 | 0.0009 | false |
| volume_liquidity | price_behavior + volume_liquidity | reject | n/a | n/a | n/a | n/a | false |
| volatility_risk | price_behavior + volatility_risk | reject | 0.0226 | 0.0273 | -0.0030 | 0.0043 | false |
| fundamental_quality | price_behavior + fundamental_quality | reject | n/a | n/a | n/a | n/a | false |
| valuation | price_behavior + valuation | reject | n/a | n/a | n/a | n/a | false |
| regime_context | price_behavior + regime_context | keep | 0.0264 | 0.0246 | 0.0008 | 0.0016 | false |

No computed candidate hid test-window degradation; every computed test delta was
non-negative. Cross-sectional context and volatility/risk were still rejected
because they failed the validation-improvement rule against the prior accepted
price-only stack.

## Information Coefficient

| bucket | validation IC | test IC |
| --- | ---: | ---: |
| price_behavior | 0.1361 | 0.0479 |
| cross_sectional_context | 0.1329 | 0.0566 |
| volatility_risk | 0.1063 | 0.0689 |
| regime_context | 0.1402 | 0.0685 |

## Comparison Rows

Computed price, cross-sectional, volatility, and regime comparisons used the
same complete split ranges for prior and candidate models:

| split | rows | min_date | max_date |
| --- | ---: | --- | --- |
| train | 108,116 | 1998-12-31 | 2021-12-31 |
| validation | 9,600 | 2022-02-02 | 2023-12-29 |
| test | 11,439 | 2024-02-01 | 2026-05-19 |

Rejected skipped buckets:

| bucket | reason | complete train rows | complete validation rows | complete test rows |
| --- | --- | ---: | ---: | ---: |
| volume_liquidity | train split has no complete rows | 0 | 0 | 0 |
| fundamental_quality | train split has no complete rows | 0 | 0 | 2,848 |
| valuation | train split has no complete rows | 0 | 0 | 2,791 |

## Notes

- `volume_liquidity` remains blocked by all-null `liq_turnover`.
- `fundamental_quality` and `valuation` remain blocked by strict-PIT/sparse
  complete-case coverage in the training and validation windows.
- `cross_sectional_context` and `volatility_risk` had positive test deltas but
  negative validation deltas; they are not accepted under the current rule.
- `regime_context` added small positive validation and test deltas to the
  price-only stack, so it remains in the smoke candidate stack.
