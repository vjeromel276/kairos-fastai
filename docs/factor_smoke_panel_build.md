# Factor Smoke Panel Build

Build date: 2026-06-20

Local database: `data/kairos-fastai.duckdb`

Output table:

```text
factor_panel_large_cap_smoke_v1
```

## Decision

Status: build complete and quality-check valid.

The large-cap smoke panel is ready for the next smoke-path step:
`FSM-004: Run Factor Panel Quality Gate`.

## Commands Run

Panel build:

```bash
python scripts/experiments/build_factor_panel.py --db data/kairos-fastai.duckdb --panel large_cap_fixed --buckets price volume volatility fundamental valuation regime cross_sectional --output-table factor_panel_large_cap_smoke_v1
```

Quality check:

```bash
python scripts/experiments/check_factor_dataset_quality.py --db data/kairos-fastai.duckdb --table factor_panel_large_cap_smoke_v1
```

## Build Result

The builder wrote:

```text
135,455 factor rows
```

Panel:

```text
large_cap_fixed
```

Buckets requested:

```text
price, volume, volatility, fundamental, valuation, regime, cross_sectional
```

Date range:

```text
1997-12-31 -> 2026-06-18
```

Ticker count:

```text
20
```

## Quality Summary

| check | result |
| --- | --- |
| duplicate `(ticker, date)` keys | 0 |
| null ticker rows | 0 |
| null date rows | 0 |
| 21-day target rows available | 135,035 |
| 21-day target null rows | 420 |
| 21-day winner mismatches | 0 |
| 5-day target rows available | 135,355 |
| 5-day target null rows | 100 |
| 5-day winner mismatches | 0 |
| quality checker result | valid |

Bucket availability from the quality checker:

| bucket | columns | rows with any value | rows with all values |
| --- | ---: | ---: | ---: |
| price_behavior | 11 | 135,435 | 130,415 |
| cross_sectional_context | 6 | 135,455 | 135,035 |
| volume_liquidity | 11 | 135,455 | 0 |
| volatility_risk | 15 | 135,055 | 130,415 |
| fundamental_quality | 9 | 3,268 | 3,268 |
| valuation | 6 | 131,759 | 3,164 |
| regime_context | 10 | 135,119 | 131,439 |

## Notes

- `liq_turnover` is null for all rows because the current smoke build does not
  join shares outstanding or market cap into the volume/liquidity bucket.
- Fundamental quality coverage is sparse under the strict point-in-time policy.
  This is expected enough to proceed to diagnostics, not enough to promote the
  bucket without further review.
- The quality checker reports `closeadj` and `volume` as unclassified columns.
  These are raw carry-through fields from the panel builder, not model-prefixed
  features.
- The build emitted pandas `FutureWarning` messages from fundamental fallback
  ratio composition. They did not block the build, but should be cleaned up if
  the warning becomes noisy or pandas behavior changes.
