# Factor Smoke Next Path

Decision date: 2026-06-20

## Decision

Choose this path:

```text
freeze the price-regime candidate, run full-stack walk-forward, then test universe generalization
```

Do not move to tree-based model work yet. Do not promote the model from the
large-cap smoke panel alone.

## Current Evidence

Positive evidence:

- The fixed-split cumulative smoke run selected
  `price_behavior + regime_context`.
- The scored table has 21,039 validation/test rows with zero duplicate
  `(ticker, date)` keys.
- Full-panel top-5 average return is 0.0254 with mean IC 0.1012.
- Validation/test split summaries remain positive:
  - validation top-5 return 0.0264, IC 0.1402
  - test top-5 return 0.0246, IC 0.0685
- Beta-adjusted top-5 average return remains positive at 0.0205 combined.
- Sector diagnostics now compute, with combined sector-neutral return 0.0130
  and max top-K sector share 0.3323.
- Average turnover is 0.1345, and cost-adjusted top-5 average return remains
  close to gross return at 0.0253.
- Selected-name liquidity is strong for the large-cap smoke panel.

Post-fix bucket evidence:

- `volume_liquidity` is now testable after treating `liq_turnover` as optional,
  but it is rejected in the cumulative stack because it degrades validation and
  test top-K return versus price-only.
- `valuation` is now testable after treating `val_fcf_yield` as optional, but
  it is rejected because validation degrades versus price-only.
- `fundamental_quality` remains unavailable in the original long train and
  validation windows under the strict PIT policy.

Remaining gaps:

- The evidence is still from a fixed 20-ticker large-cap smoke panel, not the
  broader production universe.
- The existing walk-forward report is bucket-only. The frozen
  `price_behavior + regime_context` stack still needs combined full-stack
  walk-forward evidence.
- `universe_fastai_v1` has not yet been used as a generalization test for the
  frozen candidate.

## Next Work

Continue with the open tasks in:

```text
docs/factor_smoke_experiment_backlog.md
```

Required order:

1. `FSM-014`: freeze the `price_behavior + regime_context` candidate and
   promotion criteria.
2. `FSM-015`: refresh stale post-fix smoke notes.
3. `FSM-016`: run full-stack walk-forward for the frozen candidate.
4. `FSM-017`: run the same frozen candidate on `universe_fastai_v1` as a
   generalization test.
5. `FSM-018`: record the final keep/watch/reject decision.

The larger universe is a breadth/generalization test. It should not be used to
change the candidate after seeing results or to rescue weak large-cap evidence.
