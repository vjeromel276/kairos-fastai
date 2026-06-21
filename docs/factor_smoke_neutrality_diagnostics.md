# Factor Smoke Neutrality Diagnostics

Run date: 2026-06-20

## Decision

Status: pass.

`factor_smoke_scores_v1` includes `sector`, so sector-neutral,
sector-breakdown, and top-K sector-concentration diagnostics compute. The
report preserves the combined validation/test summary and includes
validation/test split summaries under `split_summary`.

## Command Run

```bash
python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --beta-column risk_beta_spy_21d --top-k 5
```

Local report:

```text
local_artifacts/factor_smoke_v1/fsb006_neutrality_report.json
```

## Combined Results

| metric | full panel | beta adjusted | sector neutral |
| --- | ---: | ---: | ---: |
| scored rows | 21,039 | 21,039 | 21,039 |
| scored dates | 1,052 | 1,052 | 1,052 |
| top-K average return | 0.0254 | 0.0205 | 0.0130 |
| top-K win rate | 0.6042 | 0.5838 | 0.5651 |
| mean IC | 0.1012 | 0.0623 | 0.0705 |

Top-K sector concentration:

| metric | value |
| --- | ---: |
| selected count | 5,260 |
| max sector share | 0.3323 |

## Split Results

| split | rows | dates | top-K average return | top-K win rate | mean IC | beta-adjusted return |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| validation | 9,600 | 480 | 0.0264 | 0.5996 | 0.1402 | 0.0208 |
| test | 11,439 | 572 | 0.0246 | 0.6080 | 0.0685 | 0.0202 |

Sector-neutral split results:

| split | sector-neutral return | sector-neutral win rate | sector-neutral IC | max sector share |
| --- | ---: | ---: | ---: | ---: |
| validation | 0.0090 | 0.5436 | 0.1020 | 0.3179 |
| test | 0.0162 | 0.5832 | 0.0441 | 0.3444 |

## Readout

- The full-panel ranking remains positive in both validation and test.
- Beta adjustment weakens but does not erase the signal in either split.
- Sector-neutral returns are positive in both splits, but materially lower than
  unconstrained top-K returns.
- Technology is the largest top-K sector concentration in the combined report,
  with max sector share around 33%.
