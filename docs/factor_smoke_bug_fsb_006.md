# FSB-006 Split-Aware Factor Score Diagnostics

Run date: 2026-06-20

## Decision

Status: fixed.

Neutrality and turnover/capacity diagnostics now preserve the combined
validation/test summary and add a `split_summary` section when the scored table
has a `split` column. This makes validation and test behavior visible without
requiring separate scored tables.

## Commands Run

```bash
python -m compileall scripts
python -m pytest tests/test_factor_neutrality_diagnostics.py tests/test_turnover_capacity_metrics.py
python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --beta-column risk_beta_spy_21d --top-k 5
python scripts/experiments/turnover_capacity_metrics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --liquidity-column liq_adv_20d --top-k 5 --cost-bps 10
```

Local reports:

```text
local_artifacts/factor_smoke_v1/fsb006_neutrality_report.json
local_artifacts/factor_smoke_v1/fsb006_turnover_capacity_report.json
```

## Neutrality Split Summary

| split | rows | dates | top-K average return | top-K win rate | mean IC | beta-adjusted return |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| combined | 21,039 | 1,052 | 0.0254 | 0.6042 | 0.1012 | 0.0205 |
| validation | 9,600 | 480 | 0.0264 | 0.5996 | 0.1402 | 0.0208 |
| test | 11,439 | 572 | 0.0246 | 0.6080 | 0.0685 | 0.0202 |

Sector diagnostics also compute inside each split.

| split | sector-neutral return | sector-neutral win rate | sector-neutral IC | max sector share |
| --- | ---: | ---: | ---: | ---: |
| combined | 0.0130 | 0.5651 | 0.0705 | 0.3323 |
| validation | 0.0090 | 0.5436 | 0.1020 | 0.3179 |
| test | 0.0162 | 0.5832 | 0.0441 | 0.3444 |

## Turnover Split Summary

| split | rows | dates | average turnover | holding overlap | gross return | cost-adjusted return |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| combined | 21,039 | 1,052 | 0.1345 | 0.8655 | 0.0254 | 0.0253 |
| validation | 9,600 | 480 | 0.1253 | 0.8747 | 0.0264 | 0.0263 |
| test | 11,439 | 572 | 0.1415 | 0.8585 | 0.0246 | 0.0245 |

Split-level turnover resets the first holding set inside each split, so the
validation/test boundary does not add an artificial turnover observation to the
test summary.

## Readout

- Combined diagnostics remain available for a single smoke summary.
- Validation and test diagnostics are now explicit in the same report.
- Test behavior remains positive but weaker than validation on mean IC, and
  test turnover is slightly higher than validation.
