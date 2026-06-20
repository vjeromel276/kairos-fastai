# Factor Smoke Turnover And Capacity Diagnostics

Run date: 2026-06-20

## Decision

Status: pass.

The full daily turnover report is stored locally and is not committed:

```text
local_artifacts/factor_smoke_v1/turnover_capacity_smoke_report.json
```

## Command Run

```bash
python scripts/experiments/turnover_capacity_metrics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --liquidity-column liq_adv_20d --top-k 5 --cost-bps 10
```

## Results

| metric | value |
| --- | ---: |
| scored rows | 21,039 |
| selected dates | 1,052 |
| missing score dates | 0 |
| average turnover | 0.1345 |
| average holding overlap | 0.8655 |
| maximum daily turnover | 0.6000 |
| zero-turnover days | 445 |
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

Date range:

| row | date | turnover | holding overlap | gross return | cost-adjusted return |
| --- | --- | ---: | ---: | ---: | ---: |
| first | 2022-02-02 | n/a | n/a | -0.0852 | -0.0852 |
| last | 2026-05-19 | 0.0000 | 1.0000 | -0.0092 | -0.0092 |

## Readout

- Missing score days are zero.
- Average turnover is modest for a daily top-5 selection process.
- The 10 bps transaction-cost assumption has a small average impact because
  average turnover is low.
- Selected-name liquidity is high enough for this large-cap smoke panel, with
  minimum selected `liq_adv_20d` around 365 million.
