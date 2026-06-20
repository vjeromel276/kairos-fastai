# Factor Smoke Redundancy Diagnostics

Review date: 2026-06-20

Panel table:

```text
factor_panel_large_cap_smoke_v1
```

## Decision

Status: pass with review warnings.

No features were dropped in this task. The diagnostics identify redundancy and
coverage risks for model-review decisions, not automatic feature removal.

## Command Run

```bash
python scripts/experiments/feature_redundancy_diagnostics.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1
```

## Summary

| metric | result |
| --- | ---: |
| rows inspected | 135,455 |
| feature columns inspected | 68 |
| near-constant features | 1 |
| high-correlation pairs at threshold | 4 |
| missingness overlap pairs at threshold | 55 |

## Near-Constant Features

| feature | reason | review |
| --- | --- | --- |
| `liq_turnover` | all null | Do not use until shares outstanding or market-cap inputs are joined into the liquidity bucket. |

## High-Correlation Pairs

| feature A | feature B | correlation | review |
| --- | --- | ---: | --- |
| `px_return_5d` | `px_short_reversal_5d` | -1.0000 | Exact inverse by construction; keep both only for explicit reversal experiments. |
| `liq_is_price_eligible` | `liq_is_liquid` | 0.9894 | Eligibility flags are nearly redundant in this large-cap panel. |
| `qual_operating_margin` | `qual_net_margin` | 0.9859 | Related profitability measures; review after model diagnostics. |
| `liq_adv_20d` | `liq_adv_60d` | 0.9853 | ADV windows are highly correlated; this is expected. |

## Missingness Overlap

The largest missingness overlap findings are driven by:

- `liq_turnover`, which is all null.
- strict point-in-time fundamental quality features, which have sparse
  coverage.
- `val_fcf_yield`, which depends on point-in-time `sf1` cash-flow coverage.

Top missingness overlap examples:

| feature pair | both-null rate |
| --- | ---: |
| `liq_turnover` / `val_fcf_yield` | 97.66% |
| `liq_turnover` / `qual_gross_margin` | 97.59% |
| `qual_gross_margin` / `val_fcf_yield` | 97.59% |

## Bucket-Level Notes

- Volatility/risk features are internally correlated, with max absolute
  within-bucket correlation of 0.9741 and mean absolute correlation of 0.6520.
  This is expected because multiple windows and related risk measures share
  return inputs.
- Regime features are also internally correlated, with max absolute
  within-bucket correlation of 0.8696 and mean absolute correlation of 0.5484.
- Cross-bucket correlations do not show an obvious single collapse across all
  buckets, but cumulative ablations should determine whether each bucket adds
  out-of-sample ranking value.

## Follow-Up Candidates

- Consider excluding `liq_turnover` from smoke modeling until it has real
  inputs.
- Consider testing `px_return_5d` and `px_short_reversal_5d` separately because
  they are perfectly collinear.
- Review whether sparse fundamental and free-cash-flow features should be
  included in the first smoke model or isolated in diagnostics.
