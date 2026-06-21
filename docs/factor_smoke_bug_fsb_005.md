# FSB-005 Sector Context Score Diagnostics

Run date: 2026-06-20

## Decision

Status: fixed.

The local `tickers` source includes static `sector` and `industry` metadata.
The factor panel builder now carries `exchange`, `sector`, and `industry` into
the smoke panel, and the score exporter carries `sector` and `industry` into
`factor_smoke_scores_v1`. Sector neutrality diagnostics now compute instead of
skipping.

## Commands Run

```bash
python -m compileall scripts
python -m pytest tests/test_build_factor_panel.py tests/test_export_factor_scores.py tests/test_factor_neutrality_diagnostics.py
python scripts/experiments/build_factor_panel.py --db data/kairos-fastai.duckdb --panel large_cap_fixed --buckets price volume volatility fundamental valuation regime cross_sectional --output-table factor_panel_large_cap_smoke_v1
python scripts/experiments/export_factor_scores.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --output-table factor_smoke_scores_v1 --bucket-stack price regime --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --score-splits validation test --embargo 21
python scripts/experiments/factor_neutrality_diagnostics.py --db data/kairos-fastai.duckdb --table factor_smoke_scores_v1 --score-column prediction_score --target-column future_21d_return --beta-column risk_beta_spy_21d --top-k 5
```

Local reports:

```text
local_artifacts/factor_smoke_v1/fsb005_score_export_report.json
local_artifacts/factor_smoke_v1/fsb005_neutrality_report.json
```

## Metadata Coverage

Rebuilt panel coverage:

| column | non-null rows | distinct values |
| --- | ---: | ---: |
| sector | 135,455 | 7 |
| industry | 135,455 | 15 |

Score table coverage:

| metric | value |
| --- | ---: |
| scored rows | 21,039 |
| non-null sector rows | 21,039 |
| non-null industry rows | 21,039 |
| distinct sectors | 7 |
| distinct industries | 15 |

Score export optional diagnostic columns:

```text
sector
industry
risk_beta_spy_21d
liq_adv_20d
```

## Neutrality Result

Sector diagnostics status: `computed`.

| metric | value |
| --- | ---: |
| sector count | 7 |
| sector-neutral top-K average return | 0.0130 |
| sector-neutral top-K win rate | 0.5651 |
| sector-neutral mean IC | 0.0705 |
| top-K concentration selected count | 5,260 |
| max sector share | 0.3323 |

The largest top-K sector share is Technology at 33.23%.

## Readout

Sector neutrality and sector concentration are no longer blocked by missing
metadata. The classification is static ticker metadata, so it is suitable for
diagnostics now but should not be treated as point-in-time sector history.
