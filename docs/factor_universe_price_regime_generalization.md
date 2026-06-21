# Factor Universe Price-Regime Generalization

Run date: 2026-06-20

## Decision

Status: failed universe generalization.

The frozen `price_behavior + regime_context` stack was run on
`universe_fastai_v1` without changing the model, target, top-K, embargo, or
diagnostic criteria. The model beats a weak prior-return baseline, but the
actual validation and test top-5 returns are negative, remain negative after
transaction costs, and are negative after beta adjustment. This fails the
promotion criteria for universe evidence.

## Source And Panel

Source freshness check:

```bash
python scripts/pipeline/sharadar_data_sync.py --db data/kairos-fastai.duckdb --tables SEP DAILY SF1 SFP --check-only
```

Result:

- `SEP`, `DAILY`, and `SFP` were up to date at `2026-06-18`.
- `SF1` reported `needs_update`, while both local and API max dates printed as
  `2026-06-18`; this is documented as a non-blocking freshness warning because
  this frozen stack does not use SF1 features.

Universe table:

| metric | value |
| --- | ---: |
| rows | 17,895,906 |
| tickers | 12,608 |
| min date | 1998-03-27 |
| max date | 2026-06-18 |
| min daily names | 1,607 |
| max daily names | 3,542 |

The initial pandas universe build was killed with exit `137`, so the run used a
DuckDB-window builder for this specific frozen panel. The output panel starts
at `2018-01-02` with source warmup from `2016-12-15`.

```bash
python scripts/experiments/build_universe_price_regime_panel.py --db data/kairos-fastai.duckdb --source-start-date 2016-12-15 --start-date 2018-01-02 --output-table factor_panel_universe_price_regime_v1
```

Panel coverage:

| metric | value |
| --- | ---: |
| rows | 5,953,357 |
| tickers | 6,424 |
| min date | 2018-01-02 |
| max date | 2026-06-18 |
| duplicate ticker/date keys | 0 |
| non-null `risk_beta_spy_21d` rows | 5,952,861 |
| non-null `liq_adv_20d` rows | 5,952,718 |

## Score Export

```bash
python scripts/experiments/export_factor_scores.py --db data/kairos-fastai.duckdb --table factor_panel_universe_price_regime_v1 --output-table factor_universe_price_regime_scores_v1 --bucket-stack price regime --train-start 2018-01-02 --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --score-splits validation test --embargo 21
```

Score coverage:

| split | scored rows | tickers | date range |
| --- | ---: | ---: | --- |
| validation | 1,322,916 | 4,325 | 2022-02-02..2023-12-29 |
| test | 1,478,842 | 3,808 | 2024-02-01..2026-05-19 |

Training complete rows: `2,715,479`.

## Results

| split | top-5 return | win rate | IC | beta-adjusted return | sector-neutral return | avg turnover | cost-adjusted return | min ADV20 | max sector share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| validation | -0.0219 | 0.3983 | 0.0396 | -0.0254 | -0.0132 | 0.2672 | -0.0221 | 1,000,982 | 0.5675 |
| test | -0.0136 | 0.4318 | 0.0260 | -0.0214 | 0.0094 | 0.2084 | -0.0138 | 895,538 | 0.4822 |

Prior-return baseline comparison:

| split | model top-5 return | baseline top-5 return | return delta | model IC | baseline IC | IC delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| validation | -0.0219 | -0.1551 | 0.1332 | 0.0396 | -0.0045 | 0.0441 |
| test | -0.0136 | -0.0999 | 0.0863 | 0.0260 | 0.0026 | 0.0234 |

Local reports:

- `local_artifacts/factor_smoke_v1/fsm017_universe_score_export_report.json`
- `local_artifacts/factor_smoke_v1/fsm017_universe_neutrality_report.json`
- `local_artifacts/factor_smoke_v1/fsm017_universe_turnover_capacity_report.json`
- `local_artifacts/factor_smoke_v1/fsm017_universe_ranking_baseline_report.json`

## Readout

- Large-cap fixed split and full-stack walk-forward were positive, but the
  broader universe did not preserve positive top-K returns.
- Positive IC with negative top-K return means the model has some monotonic
  rank information, but the top-5 selection rule is not useful on this
  universe under the frozen criteria.
- Healthcare dominated validation top-5 selections, and the selected liquidity
  floor was much lower than the large-cap smoke panel.
- The correct next step is `FSM-018`: record the frozen candidate as failing
  universe promotion unless a review finds a process defect in this evidence.
