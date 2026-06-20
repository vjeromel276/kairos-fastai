# FSB-002 Volume Turnover Availability

Run date: 2026-06-20

## Decision

Status: fixed.

`liq_turnover` remains all-null in the large-cap smoke panel because the panel
does not provide a valid shares or market-cap input to the volume/liquidity
feature builder. It is now excluded from the required volume/liquidity model
feature set through the shared feature availability policy, and the quality gate
records it explicitly as optional and skipped.

## Commands Run

```bash
python -m compileall scripts
python -m pytest tests/test_factor_dataset_quality.py tests/test_bucket_model_harness.py tests/test_bucket_ablation_harness.py tests/test_walk_forward_factor_driver.py
python scripts/experiments/build_factor_panel.py --db data/kairos-fastai.duckdb --panel large_cap_fixed --buckets price volume volatility fundamental valuation regime cross_sectional --output-table factor_panel_large_cap_smoke_v1
python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1
python scripts/experiments/bucket_model_harness.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1 --buckets volume --train-end 2021-12-31 --validation-end 2023-12-29 --test-end 2026-06-12 --embargo 21 --top-k 5
```

Local reports:

```text
local_artifacts/factor_smoke_v1/fsb002_quality_report.txt
local_artifacts/factor_smoke_v1/fsb002_volume_bucket_report.json
```

## Quality Gate Result

The quality gate passed and records:

```text
volume_liquidity: columns=11, rows_any=135,455, rows_all=0, null_values=140,135
optional liq_turnover: status=skipped, non_null_rows=0, null_rows=135,455, reason=optional feature all null
Valid: True
```

## Volume Bucket Result

The volume-only bucket now computes with 10 required liquidity features:

```text
liq_dollar_volume
liq_is_price_eligible
liq_volume_avg_20d
liq_adv_20d
liq_rel_volume_20d
liq_volume_avg_60d
liq_adv_60d
liq_rel_volume_60d
liq_is_adv20_eligible
liq_is_liquid
```

Skipped optional feature:

```text
liq_turnover
```

Metrics:

| metric | value |
| --- | ---: |
| complete train rows | 111,976 |
| validation top-K average return | 0.0192 |
| test top-K average return | 0.0205 |

## Notes

The panel rebuild emitted the known pandas FutureWarnings from the fundamental
quality fallback path. The volume-only ridge run emitted a SciPy
`LinAlgWarning` for matrix conditioning. Both commands completed successfully.
