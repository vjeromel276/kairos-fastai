# Factor Smoke Next Path

Decision date: 2026-06-20

## Decision

Choose this path:

```text
fix data, scoring, and evaluation blockers found by the smoke run
```

Do not promote to `universe_fastai_v1` yet. Do not move to tree-based model
work yet.

## Evidence

Positive evidence:

- The fixed-split cumulative smoke run selected
  `price_behavior + regime_context`.
- The scored table has 21,039 validation/test rows with zero duplicate
  `(ticker, date)` keys.
- Full-panel top-5 average return is 0.0254 with mean IC 0.1012.
- Beta-adjusted top-5 average return remains positive at 0.0205.
- Average turnover is 0.1345, and cost-adjusted top-5 average return remains
  close to gross return at 0.0253.
- Selected-name liquidity is strong for the large-cap smoke panel.

Blocking evidence:

- `volume_liquidity`, `fundamental_quality`, and `valuation` skipped every
  walk-forward fold under the current full-bucket complete-case policy.
- `liq_turnover` is all-null in the smoke panel and blocks the full
  volume/liquidity bucket.
- Strict point-in-time fundamentals and `val_fcf_yield` are too sparse for the
  current training and validation windows when treated as mandatory.
- Sector diagnostics are unavailable because `sector` is missing from the
  scored panel.
- The evidence is from a fixed 20-ticker large-cap smoke panel, not the broader
  production universe.

## Next Work

Start a blocker-fix backlog before adding model complexity:

- Define per-bucket required and optional feature policy.
- Exclude, split out, or separately evaluate features that are all-null or too
  sparse for a given training window.
- Add sector or industry context to the factor panel or score table if source
  data is available.
- Re-run the large-cap smoke path after the bucket coverage fix.
- Promote to `universe_fastai_v1` only after the intended independent buckets
  are actually testable and neutrality diagnostics are not structurally
  missing.

Tree-based model work should wait until this coverage problem is fixed. A more
flexible model would hide the current data/evaluation issue rather than answer
whether the intended buckets add independent signal.
