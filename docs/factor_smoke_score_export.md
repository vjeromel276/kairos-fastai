# Factor Smoke Score Export

Run date: 2026-06-20

## Decision

Status: pass.

Created local scored table:

```text
factor_smoke_scores_v1
```

The table stores out-of-sample validation and test predictions for the accepted
smoke stack:

```text
price_behavior + regime_context
```

No DuckDB data file or large export artifact is committed.

## Export Command

```bash
python scripts/experiments/export_factor_scores.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --output-table factor_smoke_scores_v1 --bucket-stack price regime --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --score-splits validation test --embargo 21
```

Export summary:

| metric | value |
| --- | ---: |
| train complete rows | 108,116 |
| scored rows | 21,039 |
| duplicate `(ticker, date)` keys | 0 |
| feature count | 21 |

Scored split ranges:

| split | rows | min_date | max_date |
| --- | ---: | --- | --- |
| validation | 9,600 | 2022-02-02 | 2023-12-29 |
| test | 11,439 | 2024-02-01 | 2026-05-19 |

Available diagnostic columns:

```text
ticker, date, panel_name, future_21d_return, winner_21d,
prior_21d_return, risk_beta_spy_21d, liq_adv_20d, split,
prediction_score
```

`sector` is not available in the current smoke panel, so sector diagnostics
skip explicitly.

## Neutrality Diagnostics

Backlog test-plan command:

```bash
python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --top-k 5
```

Result:

| metric | value |
| --- | ---: |
| row count | 21,039 |
| scored dates | 1,052 |
| full-panel top-K average return | 0.0254 |
| full-panel top-K win rate | 0.6042 |
| full-panel mean IC | 0.1012 |

Sector result:

```text
skipped: sector column missing
```

Additional beta-adjusted command:

```bash
python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --beta-column risk_beta_spy_21d --top-k 5
```

Beta-adjusted result:

| metric | value |
| --- | ---: |
| beta-adjusted top-K average return | 0.0205 |
| beta-adjusted top-K win rate | 0.5838 |
| beta-adjusted mean IC | 0.0623 |

## Turnover And Capacity Diagnostics

Command:

```bash
python scripts/experiments/turnover_capacity_metrics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --top-k 5
```

Result:

| metric | value |
| --- | ---: |
| selected dates | 1,052 |
| missing score dates | 0 |
| average turnover | 0.1345 |
| average holding overlap | 0.8655 |
| gross top-K average return | 0.0254 |
| cost-adjusted top-K average return | 0.0253 |
| selected rows for liquidity | 5,260 |
| average selected `liq_adv_20d` | 7,683,873,022 |
| median selected `liq_adv_20d` | 4,431,811,093 |
| minimum selected `liq_adv_20d` | 365,473,070 |

## Notes

- The export is validation/test out-of-sample relative to the training window.
- The diagnostics currently evaluate the combined scored table. Later
  promotion work should separate validation, test, and walk-forward summaries.
- The beta-adjusted result remains positive but weaker than the unadjusted
  full-panel ranking, so beta exposure should stay under review.
