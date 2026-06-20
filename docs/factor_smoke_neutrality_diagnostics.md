# Factor Smoke Neutrality Diagnostics

Run date: 2026-06-20

## Decision

Status: pass with sector diagnostics skipped.

`factor_smoke_scores_v1` has no `sector` column, so sector-neutral,
sector-breakdown, and top-K sector-concentration diagnostics skip explicitly.
Beta-adjusted diagnostics are available through `risk_beta_spy_21d`.

## Command Run

```bash
python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --beta-column risk_beta_spy_21d --top-k 5
```

## Results

| metric | full panel | beta adjusted |
| --- | ---: | ---: |
| scored rows | 21,039 | 21,039 |
| scored dates | 1,052 | 1,052 |
| top-K average return | 0.0254 | 0.0205 |
| top-K win rate | 0.6042 | 0.5838 |
| mean IC | 0.1012 | 0.0623 |

Sector diagnostics:

```text
skipped: sector column missing
```

## Readout

- The full-panel ranking remains positive.
- Beta adjustment weakens but does not erase the signal.
- Sector dominance cannot be assessed until sector data is added to the scored
  panel.
- Because sector is unavailable, no one-sector top-pick concentration decision
  can be made from this smoke run.
