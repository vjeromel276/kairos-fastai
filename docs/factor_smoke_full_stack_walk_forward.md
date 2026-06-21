# Factor Smoke Full-Stack Walk-Forward

Run date: 2026-06-20

## Decision

Status: pass for large-cap full-stack walk-forward.

The frozen `price_behavior + regime_context` stack computes across all 24
walk-forward folds as a combined model. Aggregate validation and test metrics
are positive, beat the prior-return baseline, and remain positive after beta,
sector-neutral, turnover, and transaction-cost diagnostics.

This is still large-cap smoke evidence, not final promotion evidence. The later
`universe_fastai_v1` generalization test failed and is recorded in
`docs/factor_universe_price_regime_generalization.md`.

## Command Run

```bash
python scripts/experiments/walk_forward_factor_driver.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets price regime --evaluation-mode stack --train-size 756 --validation-size 252 --test-size 252 --step-size 252 --embargo 21 --top-k 5 --cost-bps 10
```

Local report:

```text
local_artifacts/factor_smoke_v1/fsm016_price_regime_full_stack_walk_forward_report.json
```

## Fold Coverage

| metric | value |
| --- | ---: |
| folds | 24 |
| computed folds | 24 |
| skipped folds | 0 |

Date coverage:

| fold | train | validation | test |
| --- | --- | --- | --- |
| first | 1997-12-31..2000-12-28 | 2000-12-29..2002-01-04 | 2002-01-07..2003-01-06 |
| last | 2021-01-13..2024-01-16 | 2024-01-17..2025-01-16 | 2025-01-17..2026-01-26 |

## Aggregate Stack Metrics

| split | top-K avg return | top-K win rate | mean IC | baseline return delta | baseline IC delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| validation | 0.0210 | 0.5927 | 0.0424 | 0.0045 | 0.0360 |
| test | 0.0227 | 0.6028 | 0.0587 | 0.0056 | 0.0486 |

## Aggregate Diagnostics

Neutrality:

| split | beta-adjusted top-K return | sector-neutral top-K return | max sector share |
| --- | ---: | ---: | ---: |
| validation | 0.0215 | 0.0151 | 0.3808 |
| test | 0.0214 | 0.0153 | 0.3802 |

Turnover, cost, and liquidity:

| split | avg turnover | cost-adjusted top-K return | minimum selected `liq_adv_20d` |
| --- | ---: | ---: | ---: |
| validation | 0.1018 | 0.0209 | 248,591,025 |
| test | 0.1101 | 0.0226 | 283,843,045 |

## Readout

- The frozen stack passes the large-cap full-stack walk-forward stop/continue
  rules from `docs/factor_price_regime_promotion_criteria.md`.
- Test evidence is positive and stronger than validation on top-K return and
  IC.
- Transaction-cost impact remains small at the 10 bps proxy.
- Sector-neutral results remain positive, so the signal is not erased by
  neutralizing sector context.
- Liquidity remains strong for the large-cap smoke panel.
- The appropriate decision from this step was `watch`; later
  breadth/generalization evidence failed on `universe_fastai_v1`.
