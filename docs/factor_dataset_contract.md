# Factor Dataset Contract

This contract defines the table shape and metadata needed for multi-factor
equity ranking experiments. It applies to every factor panel built from the
multi-factor backlog.

## Table Grain

The model-ready factor panel must have exactly one row per:

```text
ticker, date
```

Rules:

- `ticker` is uppercase and non-null.
- `date` is a DuckDB `DATE` and represents prediction date `T`.
- All feature values must be knowable at or before `date`.
- No feature may use the target horizon or any future row.
- Duplicate `(ticker, date)` rows are invalid.

Recommended default table name:

```text
factor_panel_v1
```

## Required Columns

| column | type | description |
| --- | --- | --- |
| `ticker` | `VARCHAR` | security identifier |
| `date` | `DATE` | prediction date `T` |
| `panel_name` | `VARCHAR` | source panel, such as `large_cap_fixed` or `universe_fastai_v1` |
| `future_21d_return` | `DOUBLE` | primary adjusted forward return over 21 trading rows |
| `winner_21d` | `BIGINT` | `1` when `future_21d_return > 0`, else `0`; null when target unavailable |
| `future_5d_return` | `DOUBLE` | secondary adjusted forward return over 5 trading rows |
| `winner_5d` | `BIGINT` | `1` when `future_5d_return > 0`, else `0`; null when target unavailable |

Recommended baseline columns:

| column | type | description |
| --- | --- | --- |
| `prior_21d_return` | `DOUBLE` | trailing adjusted 21-trading-row return through `T` |
| `prior_5d_return` | `DOUBLE` | trailing adjusted 5-trading-row return through `T` |
| `dollar_volume` | `DOUBLE` | `closeadj * volume` on date `T`, when available |
| `adv_20` | `DOUBLE` | trailing 20-row average dollar volume through `T` |
| `adv_60` | `DOUBLE` | trailing 60-row average dollar volume through `T` |

Optional metadata columns:

| column | type | description |
| --- | --- | --- |
| `exchange` | `VARCHAR` | exchange metadata used for diagnostics or universe filters |
| `sector` | `VARCHAR` | sector metadata; static until point-in-time sector history exists |
| `industry` | `VARCHAR` | industry metadata; static until point-in-time industry history exists |
| `is_large_cap_smoke` | `BOOLEAN` | true for the fixed large-cap build/debug panel |

## Target Rules

Targets use adjusted prices.

For ticker `i` on prediction date `T`:

```text
future_21d_return = closeadj[T+21] / closeadj[T] - 1
future_5d_return  = closeadj[T+5]  / closeadj[T] - 1
```

Rules:

- The last `horizon` rows for each ticker have null target values.
- Target calculations never cross ticker boundaries.
- If a future adjusted close is missing, the corresponding target is null.
- Winner labels are null when the corresponding forward return is null.
- Models may train on either horizon, but 21 trading days is the primary target
  and 5 trading days is a secondary diagnostic target.

## Feature Bucket Prefixes

Feature names should use stable prefixes by bucket:

| bucket | prefix | examples |
| --- | --- | --- |
| price behavior | `px_` | `px_return_21d`, `px_ma_dist_63d`, `px_drawdown_252d` |
| cross-sectional context | `xs_` | `xs_px_return_21d_rank`, `xs_sector_return_21d_z` |
| volume/liquidity | `liq_` | `liq_dollar_volume`, `liq_rel_volume_20d` |
| volatility/risk | `risk_` | `risk_vol_63d`, `risk_beta_spy_252d` |
| fundamental quality | `qual_` | `qual_gross_margin`, `qual_roe`, `qual_debt_to_assets` |
| valuation | `val_` | `val_pe`, `val_pb`, `val_sales_yield` |
| regime context | `regime_` | `regime_spy_trend_200d`, `regime_spy_vol_63d` |
| optional legacy RSI | `rsi_` | `rsi_14`, `rsi_slope_5` |

Raw source columns should not be mixed into model feature columns unless they
are intentionally promoted with a bucket prefix. For example, use
`liq_dollar_volume`, not bare `dollar_volume`, when the field is model input.

## Feature Manifest Contract

Every factor panel build should have a small manifest that maps features to
their origin and leakage policy. The manifest may be JSON, Markdown, or a DuckDB
table, but it must contain these fields:

| field | description |
| --- | --- |
| `feature_name` | exact model-ready column name |
| `bucket` | one of the reviewed buckets |
| `source_tables` | source tables used to create the feature |
| `source_columns` | source columns used where practical |
| `availability_policy` | how the feature is known by `date` |
| `max_lookback_trading_days` | maximum trading-row lookback required |
| `uses_market_proxy` | whether the feature depends on `SPY` |
| `null_reason` | expected null behavior such as warmup, missing source, blocked PIT policy |

Recommended manifest table name:

```text
factor_feature_manifest_v1
```

## Bucket Availability Policy

| bucket | immediate policy |
| --- | --- |
| price behavior | Safe when built from `sep_base` rows through `T`. |
| cross-sectional context | Safe for date-level ranks computed only within date `T`; sector-relative diagnostics remain static-metadata caveats. |
| volume/liquidity | Safe when built from `sep_base` rows through `T`. |
| volatility/risk | Safe when rolling windows end at `T`; `SPY` comes from `sfp`. |
| fundamental quality | Usable only through the documented SF1 point-in-time policy: `datekey` availability, fallback report-date lag, and `lastupdated` gating. |
| valuation | Daily ratios from `daily` are usable with documented caution; reconstructed SF1 valuation is blocked until SF1 PIT policy exists. |
| regime context | Safe for `SPY` trend/drawdown/volatility from `sfp` through `T`; breadth requires a reviewed panel. |

## Null Handling

Nulls are expected and should not be blindly filled.

Allowed null causes:

- warmup windows for rolling features
- insufficient future rows for targets
- missing source data on a ticker/date
- feature bucket intentionally unavailable under point-in-time policy
- missing market proxy date

Invalid null causes:

- failed joins caused by inconsistent ticker/date keys
- silent missing target rows in the middle of a ticker history
- feature columns absent from the manifest

Model code should drop rows with missing required features and targets for the
specific run, but dataset builders should preserve nulls so quality checks can
diagnose coverage.

## Panel Contract

Supported panels:

| panel_name | use |
| --- | --- |
| `large_cap_fixed` | build/debug/smoke tests |
| `universe_fastai_v1` | promotion-quality validation after universe review |

Rules:

- Panel selection must be explicit in CLI runs.
- `universe_fastai_v1` use must not happen accidentally by default.
- A model result must record the `panel_name`.
- Promotion decisions require `universe_fastai_v1` or another reviewed
  investable universe, not only `large_cap_fixed`.

## Validation Requirements

A valid factor panel must pass these checks before modeling:

- one row per `(ticker, date)`
- non-null `ticker` and `date`
- target nulls only where the future horizon is unavailable
- feature columns are listed in the manifest
- bucket-level null rates are reported
- source date ranges are reported
- market-proxy coverage is reported when `SPY` features are requested
- no blocked point-in-time bucket is included as model input

## Output Contract For Model Runs

Every model run should record:

- panel name
- selected buckets
- feature count
- target horizon
- train/validation/test date ranges
- embargo
- model type and seed
- metrics path
- score/prediction artifact path when produced
- source freshness status or explicit skip reason
