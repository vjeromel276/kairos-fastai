# Factor Smoke Quality Gate

Review date: 2026-06-20

Panel table:

```text
factor_panel_large_cap_smoke_v1
```

## Decision

Status: pass with warnings.

No blocking dataset-quality issue was found. The smoke panel can proceed to
redundancy diagnostics and model diagnostics.

## Command Run

```bash
python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1
```

## Gate Results

| check | result |
| --- | --- |
| quality checker valid | yes |
| rows | 135,455 |
| tickers | 20 |
| panels | 1 |
| date range | 1997-12-31 to 2026-06-18 |
| duplicate `(ticker, date)` keys | 0 |
| null ticker rows | 0 |
| null date rows | 0 |
| 21-day unexpected winner nulls | 0 |
| 21-day unexpected winner values | 0 |
| 21-day invalid winner values | 0 |
| 5-day unexpected winner nulls | 0 |
| 5-day unexpected winner values | 0 |
| 5-day invalid winner values | 0 |

Target availability:

| target | available rows | null rows |
| --- | ---: | ---: |
| `future_21d_return` | 135,035 | 420 |
| `future_5d_return` | 135,355 | 100 |

The target null counts match the expected last-horizon rows per ticker:

- `20 tickers * 21 rows = 420`
- `20 tickers * 5 rows = 100`

## Bucket Coverage

| bucket | columns | rows with any value | rows with all values | review |
| --- | ---: | ---: | ---: | --- |
| price_behavior | 11 | 135,435 | 130,415 | expected rolling-window warmup |
| cross_sectional_context | 6 | 135,455 | 135,035 | expected target-period warmup alignment |
| volume_liquidity | 11 | 135,455 | 0 | all rows fail `rows_all` because `liq_turnover` is null |
| volatility_risk | 15 | 135,055 | 130,415 | expected rolling-window warmup |
| fundamental_quality | 9 | 3,268 | 3,268 | sparse under strict point-in-time policy |
| valuation | 6 | 131,759 | 3,164 | daily ratios broad; `val_fcf_yield` sparse |
| regime_context | 10 | 135,119 | 131,439 | expected SPY rolling-window warmup |

## Warnings

- `liq_turnover` is null for all rows because the current smoke build does not
  provide shares outstanding or market-cap inputs to the volume/liquidity
  feature bucket.
- Fundamental quality is sparse. This is acceptable for smoke diagnostics but
  should not be treated as promotion-quality evidence without reviewing PIT
  coverage and row loss.
- `val_fcf_yield` is sparse for the same PIT/fundamental availability reason.
- `closeadj` and `volume` are reported as unclassified columns. They are raw
  carry-through fields from the builder, not model-prefixed features.

## Blockers

None for the large-cap smoke path.
