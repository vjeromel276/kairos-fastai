# Multi-Factor Source Inventory

Inventory date: 2026-06-20

Local database: `data/kairos-fastai.duckdb`

This inventory maps the reviewed multi-factor feature buckets to currently
available local DuckDB source tables and identifies point-in-time risks before
feature implementation starts.

## Audit Evidence

Command:

```bash
python scripts/fastai_reset/audit_source_db.py --db data/kairos-fastai.duckdb
```

Core source state:

| table | rows | min_date | max_date | entity_count | inventory use |
| --- | ---: | --- | --- | ---: | --- |
| `sep_base` | 46,717,977 | 1997-01-02 | 2026-06-12 | 22,738 tickers | common-stock price, volume, adjusted returns |
| `daily` | 39,804,583 | 1998-12-01 | 2026-06-12 | 17,559 tickers | daily valuation ratios |
| `sf1` | 5,912,534 | 1990-06-06 | 2026-06-12 | 18,014 tickers | fundamentals, quality, valuation inputs |
| `sf2` | 11,522,713 | 2008-01-02 | 2026-06-12 | 16,223 tickers | insider transactions; not first-stack scope |
| `sfp` | 15,223,402 | 1997-12-31 | 2026-06-12 | 9,462 tickers | ETF/fund prices, including `SPY` |
| `sf3` | 46,829,931 | 2013-06-30 | 2026-03-31 | 29,101 tickers | institutional holdings; not first-stack scope |
| `sf3a` | 654,485 | 2013-06-30 | 2026-03-31 | 30,722 tickers | aggregate institutional holdings; not first-stack scope |
| `sf3b` | 296,207 | 2013-06-30 | 2026-03-31 | 13,174 investors | investor holdings; not first-stack scope |
| `tickers` | 62,141 | none | none | 31,334 tickers | metadata, sector, industry, listing filters |
| `sharadar_actions` | 664,333 | 1997-12-31 | 2026-06-15 | 32,261 tickers | corporate actions reference |
| `sharadar_events` | 2,526,536 | 1993-11-08 | 2026-06-12 | 17,796 tickers | event flags; not first-stack scope |
| `sharadar_metrics` | 31,314 | 1997-12-31 | 2026-06-12 | 31,313 tickers | current/latest metrics; avoid for historical panel features |
| `sharadar_sp500` | 59,158 | 1957-03-04 | 2026-06-12 | 1,198 tickers | S&P 500 membership changes |
| `trading_calendar` | 7,408 | 1997-01-02 | 2026-06-12 | n/a | trading-day alignment |

Duplicate key checks in the audit reported zero duplicate `(ticker, date)` keys
for `sep_base` and `daily`.

## Market Proxy

Use `SPY` as the first market proxy, but source it from `sfp`, not `sep_base`.

Evidence:

| table | ticker | min_date | max_date | rows | decision |
| --- | --- | --- | --- | ---: | --- |
| `sep_base` | `SPY` | 1997-01-02 | 2025-11-19 | 7,268 | stale for current proxy work |
| `sfp` | `SPY` | 1997-12-31 | 2026-06-12 | 7,156 | preferred `SPY` source |

Policy:

- `SPY` regime, beta, and market-relative features should join from `sfp`.
- If `SPY` is missing on a date, market-proxy features for that date should be
  null or skipped.
- Do not forward-fill unknown future proxy data.

## Panel Sources

Two panels are planned:

| panel | status | use |
| --- | --- | --- |
| fixed large-cap panel | ready as a configured ticker list | build/debug/smoke tests |
| `universe_fastai_v1` | SQL exists, table is not currently present in local DB | promotion-quality validation after build and review |

Recommended fixed large-cap smoke list:

```text
AAPL MSFT AMZN GOOGL META NVDA JPM XOM UNH WMT
PG JNJ HD MA BAC KO PFE CSCO CVX ORCL
```

`scripts/tables/sql/build_universe_fastai_v1.sql` builds
`universe_fastai_v1` from `sep_base` and `tickers`. It uses adjusted prices,
volume, exchange/category filters, sector/industry metadata, and 20/60-day
dollar-volume filters. Before it is used for promotion-quality validation, the
universe contract should be reviewed for point-in-time metadata risk because
`tickers` is a metadata table rather than a daily point-in-time membership
history.

## Bucket Mapping

| bucket | primary sources | ready for first implementation? | point-in-time stance |
| --- | --- | --- | --- |
| price behavior | `sep_base`, `trading_calendar`; optional legacy RSI experiment code | yes | Use `closeadj`, `volume`, and date `T`; rolling windows must only use rows through `T`. |
| cross-sectional context | built factor panel, `tickers`, `sfp`/`SPY` | partially | Date-level ranks are safe if computed per date. Sector-relative features can use `tickers.sector` for diagnostics, but sector metadata is not fully point-in-time. |
| volume/liquidity | `sep_base`, future `universe_fastai_v1` | yes | Use contemporaneous `closeadj * volume` and trailing averages through `T`. |
| volatility/risk | `sep_base`, `sfp`/`SPY`, `trading_calendar` | yes | Realized volatility and beta must use lagged rolling windows ending at `T`. |
| fundamental quality | `sf1` | blocked until PIT policy is explicit | Prefer `datekey` as availability date; avoid `calendardate` or `reportperiod` as availability dates. Restatement/`lastupdated` policy must be defined before modeling. |
| valuation | `daily`; optionally `sf1` + `sep_base` | partially | `daily` ratios are date-stamped and easiest for first valuation features. Ratios may still reflect vendor restatements; use with caution and document this risk. |
| regime context | `sfp`/`SPY`, `sep_base`, future panel breadth | yes for SPY regimes; breadth later | SPY trend/drawdown/volatility can be known by `T`; breadth requires a reviewed panel build. |

## Source Table Notes

### `sep_base`

Columns:

```text
ticker, date, open, high, low, close, volume, closeadj, closeunadj, lastupdated
```

Use for common-stock price behavior, adjusted return targets, volume/liquidity,
realized volatility, and drawdown. Use `closeadj` for returns and target
construction.

### `sfp`

Columns:

```text
ticker, date, open, high, low, close, volume, closeadj, closeunadj, lastupdated
```

Use for ETF/fund proxy prices. `SPY` should come from this table.

### `daily`

Columns:

```text
ticker, date, lastupdated, ev, evebit, evebitda, marketcap, pb, pe, ps
```

Use for first-pass valuation features because it provides daily date-stamped
ratios. Treat this as easier and safer than reconstructing ratios from raw
fundamentals at first, but still document possible restatement/vendor revision
risk.

### `sf1`

Important date columns:

```text
calendardate, datekey, reportperiod, lastupdated
```

Important feature candidates include:

```text
grossmargin, netmargin, ebitdamargin, roa, roe, roic, revenue, revenueusd,
gp, ebit, ebitda, netinc, fcf, assets, equity, debt, liabilities, marketcap,
ev, pe, pb, ps
```

Use `datekey` as the earliest candidate availability date. Do not use
`calendardate` or `reportperiod` as if they were known to the market on that
date. Before fundamental quality or reconstructed valuation features are used,
define whether `lastupdated` must be less than or equal to prediction date `T`
or whether a conservative reporting lag is sufficient.

### `tickers`

Useful metadata:

```text
ticker, exchange, category, sector, industry, scalemarketcap, scalerevenue,
currency, location, firstpricedate, lastpricedate
```

Use for filters and diagnostics. Treat sector/industry as static metadata until
a point-in-time metadata source is available. Static sector use is acceptable
for early diagnostics, not as unqualified promotion evidence.

### `sharadar_metrics`

Columns include:

```text
beta1y, beta5y, high52w, low52w, ma200d, ma50d, return1y, returnytd,
volumeavg1m, volumeavg3m
```

This table has roughly one row per ticker in the local DB and should not be
treated as a historical daily panel for model training. Prefer computing rolling
metrics directly from `sep_base` and `sfp`.

### `sf3`, `sf3a`, `sf3b`

Institutional holdings tables are available through 2026-03-31, but they are
not part of the first feature stack. If used later, holdings availability must
account for reporting delay rather than treating `calendardate` as immediately
known.

## Readiness Summary

Ready for immediate feature implementation:

- price behavior from `sep_base`
- volume/liquidity from `sep_base`
- volatility/risk from `sep_base` plus `SPY` from `sfp`
- SPY regime features from `sfp`
- date-level cross-sectional ranks after a factor panel exists

Ready only with caution:

- valuation from `daily`
- sector-relative diagnostics from static `tickers.sector`

Blocked until a point-in-time policy is written:

- fundamental quality from `sf1`
- reconstructed valuation from `sf1`
- institutional holdings from `sf3`, `sf3a`, or `sf3b`

Blocked until table build/review:

- promotion-quality `universe_fastai_v1` panel
