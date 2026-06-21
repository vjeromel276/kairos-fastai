# Factor Smoke Turnover And Capacity Diagnostics

Run date: 2026-06-20

## Decision

Status: pass.

The turnover/capacity report preserves the combined validation/test summary and
adds validation/test split summaries under `split_summary`.

The full daily turnover report is stored locally and is not committed:

```text
local_artifacts/factor_smoke_v1/fsb006_turnover_capacity_report.json
```

## Command Run

```bash
python scripts/experiments/turnover_capacity_metrics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --liquidity-column liq_adv_20d --top-k 5 --cost-bps 10
```

## Combined Results

| metric | value |
| --- | ---: |
| scored rows | 21,039 |
| selected dates | 1,052 |
| missing score dates | 0 |
| average turnover | 0.1345 |
| average holding overlap | 0.8655 |
| gross top-K average return | 0.0254 |
| cost-adjusted top-K average return | 0.0253 |
| cost assumption | 10 bps |

Liquidity summary for selected top-K rows:

| metric | value |
| --- | ---: |
| selected rows | 5,260 |
| average `liq_adv_20d` | 7,683,873,022 |
| median `liq_adv_20d` | 4,431,811,093 |
| minimum `liq_adv_20d` | 365,473,070 |

## Split Results

| split | rows | dates | average turnover | holding overlap | gross return | cost-adjusted return |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| validation | 9,600 | 480 | 0.1253 | 0.8747 | 0.0264 | 0.0263 |
| test | 11,439 | 572 | 0.1415 | 0.8585 | 0.0246 | 0.0245 |

Split liquidity summary:

| split | selected rows | average `liq_adv_20d` | median `liq_adv_20d` | minimum `liq_adv_20d` |
| --- | ---: | ---: | ---: | ---: |
| validation | 2,400 | 5,565,736,818 | 4,191,839,032 | 365,473,070 |
| test | 2,860 | 9,461,329,977 | 4,516,485,658 | 738,223,002 |

## Readout

- Missing score days are zero in both validation and test.
- Average turnover is modest for a daily top-5 selection process.
- Test turnover is slightly higher than validation turnover.
- The 10 bps transaction-cost assumption has a small average impact because
  average turnover is low.
- Selected-name liquidity remains high in both splits.
