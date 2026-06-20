# Fundamental Quality Feature Policy

This policy applies to MFF-012 and any factor panel that uses `qual_` features
from Sharadar `sf1`.

## Availability Rules

Use this order for deciding when an `sf1` row may be joined to a prediction
date `T`:

1. Prefer `datekey` as the filing/availability date.
2. If `datekey` is unavailable, use `reportperiod` or `calendardate` plus a
   conservative reporting lag. The current default lag is 90 calendar days.
3. If `lastupdated` is present, require `lastupdated <= T` by default. The
   effective availability date is the later of the filing date and
   `lastupdated`.

The join must be an as-of join by ticker where the selected fundamental row has
`availability_date <= T`. No row may be joined from a future filing,
future report period, or future vendor update.

## Feature Scope

The first quality bucket exposes these model-ready columns:

```text
qual_gross_margin
qual_operating_margin
qual_net_margin
qual_roa
qual_roe
qual_roic
qual_revenue_growth
qual_earnings_growth
qual_debt_to_assets
```

When direct ratios are missing, the builder may compute ratios from source
components such as revenue, gross profit, EBIT, net income, assets, equity, and
debt. Zero denominators produce null features.

## Known Limits

This policy is intentionally conservative. Requiring `lastupdated <= T` can
reduce historical coverage because restated or vendor-corrected rows are not
treated as available before the update date. A future task may compare this
strict policy with a filing-date-only policy, but promotion-quality evidence
must record which policy was used.
