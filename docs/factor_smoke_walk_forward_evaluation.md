# Factor Smoke Walk-Forward Evaluation

Run date: 2026-06-20

## Decision

Status: pass for bucket-only walk-forward.

The walk-forward driver aggregates bucket-only models across repeated
chronological folds. After the feature availability fixes, volume/liquidity and
valuation compute across all folds. Fundamental quality still skips every fold
because strict PIT features do not have long-split training coverage.

This run is bucket-only. It does not answer whether the combined
`price_behavior + regime_context` stack is stable; that is tracked separately
as `FSM-016`.

Full local report:

```text
local_artifacts/factor_smoke_v1/fsb001_walk_forward_report.json
```

## Command Run

```bash
python scripts/experiments/walk_forward_factor_driver.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price volume volatility fundamental valuation regime cross_sectional --train-size 756 --validation-size 252 --test-size 252 --step-size 252 --embargo 21 --top-k 5
```

Fold count:

```text
24
```

Date coverage:

| fold | train | validation | test |
| --- | --- | --- | --- |
| first | 1997-12-31..2000-12-28 | 2000-12-29..2002-01-04 | 2002-01-07..2003-01-06 |
| last | 2021-01-13..2024-01-16 | 2024-01-17..2025-01-16 | 2025-01-17..2026-01-26 |

Every fold keeps training dates before validation dates and validation dates
before test dates.

## Aggregate Metrics

| bucket | status counts | validation top-K avg return | validation win rate | validation IC | test top-K avg return | test win rate | test IC |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| price_behavior | computed 24 | 0.0214 | 0.5950 | 0.0354 | 0.0222 | 0.6040 | 0.0478 |
| cross_sectional_context | computed 24 | 0.0203 | 0.5953 | 0.0429 | 0.0232 | 0.6063 | 0.0558 |
| volume_liquidity | computed 24 | 0.0218 | 0.5970 | 0.0220 | 0.0216 | 0.6054 | 0.0321 |
| volatility_risk | computed 24 | 0.0188 | 0.6014 | 0.0154 | 0.0185 | 0.5929 | 0.0074 |
| fundamental_quality | skipped 24 | n/a | n/a | n/a | n/a | n/a | n/a |
| valuation | computed 24 | 0.0165 | 0.5934 | 0.0056 | 0.0189 | 0.6063 | 0.0338 |
| regime_context | computed 24 | 0.0181 | 0.5937 | n/a | 0.0183 | 0.5968 | n/a |

## Readout

- `price_behavior` remains stable across validation and test folds.
- `cross_sectional_context` has the strongest bucket-only test average, but it
  was rejected in the cumulative fixed-split ablation because it did not
  improve validation versus price-only.
- `volume_liquidity` is now testable across all folds but did not earn a
  cumulative stack keep decision.
- `valuation` is now testable across all folds but has weaker validation
  evidence than price behavior.
- `volatility_risk` is weaker in aggregate and has low test IC.
- `regime_context` has positive top-K returns but undefined IC in aggregate
  because date-level regime features often produce identical cross-sectional
  scores within a date.
- `fundamental_quality` still needs either longer strict-PIT coverage or a
  separately scoped recent-only experiment.

## Follow-Up

Run a full-stack walk-forward diagnostic for the frozen
`price_behavior + regime_context` candidate before using this smoke evidence to
move to `universe_fastai_v1`.
