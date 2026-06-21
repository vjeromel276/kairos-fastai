# Factor Smoke Cumulative Ablations

Run date: 2026-06-20

Panel table:

```text
factor_panel_large_cap_smoke_v1
```

## Decision

Status: pass.

The cumulative smoke harness records an explicit `keep`, `watch`, or `reject`
recommendation for every candidate step. After the feature availability fixes,
volume/liquidity and valuation are testable but rejected. Fundamental quality
still rejects as skipped because strict point-in-time features have no complete
train or validation rows in the long split.

Accepted smoke stack:

```text
price_behavior + regime_context
```

This remains a `watch` candidate, not a promoted model. It needs full-stack
walk-forward evidence and `universe_fastai_v1` generalization evidence.

## Command Run

```bash
python scripts/experiments/bucket_ablation_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --bucket-order price cross_sectional volume volatility fundamental valuation regime --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
```

Post-fix report:

```text
local_artifacts/factor_smoke_v1/fsb001_cumulative_ablation_report.json
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
| volume_liquidity | price_behavior + volume_liquidity | reject | 0.0198 | 0.0194 | -0.0058 | -0.0036 | true |
| volatility_risk | price_behavior + volatility_risk | reject | 0.0226 | 0.0273 | -0.0030 | 0.0043 | false |
| fundamental_quality | price_behavior + fundamental_quality | reject | n/a | n/a | n/a | n/a | false |
| valuation | price_behavior + valuation | reject | 0.0198 | 0.0241 | -0.0058 | 0.0011 | false |
| regime_context | price_behavior + regime_context | keep | 0.0264 | 0.0246 | 0.0008 | 0.0016 | false |

## Information Coefficient

| bucket | validation IC | test IC |
| --- | ---: | ---: |
| price_behavior | 0.1361 | 0.0479 |
| cross_sectional_context | 0.1329 | 0.0566 |
| volume_liquidity | 0.0904 | 0.0479 |
| volatility_risk | 0.1063 | 0.0689 |
| valuation | 0.1039 | 0.0597 |
| regime_context | 0.1402 | 0.0685 |

## Optional Feature Handling

| bucket | candidate status | skipped optional |
| --- | --- | --- |
| volume_liquidity | computed | `liq_turnover` |
| valuation | computed | `val_fcf_yield` |

Rejected skipped buckets:

| bucket | reason | complete train rows | complete validation rows | complete test rows |
| --- | --- | ---: | ---: | ---: |
| fundamental_quality | train split has no complete rows | 0 | 0 | 2,848 |

## Readout

- `price_behavior` is the base accepted stack.
- `regime_context` adds small positive validation and test deltas and remains
  in the frozen smoke candidate stack.
- `cross_sectional_context`, `volatility_risk`, and `valuation` have positive
  test deltas but negative validation deltas, so they are rejected under the
  current stack rule.
- `volume_liquidity` is now testable but degrades both validation and test
  top-K return versus price-only.
- `fundamental_quality` remains a long-split coverage problem under strict PIT
  policy.
