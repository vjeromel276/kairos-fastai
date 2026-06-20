# Valuation Feature Policy

This policy applies to MFF-013 and `val_` model features.

## Source Alignment

Daily valuation ratios from `daily` must be joined on the exact prediction
date `T` by `(ticker, date)`. The builder does not forward-fill missing daily
ratio rows.

Cash-flow yield is optional because it combines:

- a numerator from `sf1`, joined with the same point-in-time policy used by
  MFF-012; and
- a denominator from `daily.marketcap`, aligned to prediction date `T`.

If either side is missing or the denominator is zero, cash-flow yield is null.

## Feature Scope

The first valuation bucket exposes these model-ready columns:

```text
val_earnings_yield
val_sales_yield
val_book_yield
val_ebit_ev_yield
val_ebitda_ev_yield
val_fcf_yield
```

Daily ratio fields are converted to yields by inversion. For example,
`val_earnings_yield = 1 / pe`. Negative earnings ratios remain negative
signals. Zero denominators produce nulls.

## Extreme Values

The builder clips valuation yield features to configurable bounds. The default
cap is:

```text
-10.0 <= valuation yield <= 10.0
```

This cap is deliberately wide. It prevents pathological near-zero denominators
from dominating model input while preserving ordinary negative and positive
valuation signals.
