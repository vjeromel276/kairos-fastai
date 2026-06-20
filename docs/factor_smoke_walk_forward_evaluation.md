# Factor Smoke Walk-Forward Evaluation

Run date: 2026-06-20

## Decision

Status: pass with skipped sparse buckets.

The walk-forward driver now aggregates skipped bucket folds without failing.
The full JSON report is stored locally and is not committed:

```text
local_artifacts/factor_smoke_v1/walk_forward_smoke_report.json
```

This run evaluates bucket-only models across repeated chronological folds. It
does not replace the cumulative stack decision from the fixed split.

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
| volume_liquidity | skipped 24 | n/a | n/a | n/a | n/a | n/a | n/a |
| volatility_risk | computed 24 | 0.0188 | 0.6014 | 0.0154 | 0.0185 | 0.5929 | 0.0074 |
| fundamental_quality | skipped 24 | n/a | n/a | n/a | n/a | n/a | n/a |
| valuation | skipped 24 | n/a | n/a | n/a | n/a | n/a | n/a |
| regime_context | computed 24 | 0.0181 | 0.5937 | n/a | 0.0183 | 0.5968 | n/a |
| cross_sectional_context | computed 24 | 0.0203 | 0.5953 | 0.0429 | 0.0232 | 0.6063 | 0.0558 |

## Readout

- `price_behavior` is stable across validation and test folds.
- `cross_sectional_context` has the strongest test average among computed
  bucket-only folds, but the fixed-split cumulative ablation rejected it
  because it failed the validation-improvement rule versus price-only.
- `volatility_risk` is weaker in aggregate and has low test IC.
- `regime_context` has positive top-K returns but undefined IC in aggregate
  because date-level regime features often produce identical cross-sectional
  scores within a date.
- `volume_liquidity`, `fundamental_quality`, and `valuation` skipped in every
  fold because their full-bucket complete-case training rows were unavailable.

## Follow-Up

The skipped bucket pattern reinforces the need for a per-bucket required-feature
policy before treating sparse/full-null fields as mandatory inputs.
