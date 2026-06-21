# Factor Smoke Next Path

Decision date: 2026-06-20

## Decision

Completed path:

```text
freeze the price-regime candidate, run full-stack walk-forward, then test universe generalization
```

Do not move to tree-based model work from this candidate. Do not promote the
model from the large-cap smoke panel alone.

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
- Full-stack large-cap walk-forward passed, with aggregate validation top-5
  return 0.0210 and test top-5 return 0.0227.

Negative universe evidence:

- The frozen stack was tested on `universe_fastai_v1`.
- Universe validation top-5 return was -0.0219, and universe test top-5 return
  was -0.0136.
- Universe cost-adjusted returns remained negative in validation and test.
- Universe IC was positive, and the model beat a weak prior-return baseline,
  but the top-5 selection rule did not generalize.

Post-fix bucket evidence:

- `volume_liquidity` is now testable after treating `liq_turnover` as optional,
  but it is rejected in the cumulative stack because it degrades validation and
  test top-K return versus price-only.
- `valuation` is now testable after treating `val_fcf_yield` as optional, but
  it is rejected because validation degrades versus price-only.
- `fundamental_quality` remains unavailable in the original long train and
  validation windows under the strict PIT policy.

Remaining gap:

- Record the final `keep`, `watch`, or `reject` decision for the frozen
  candidate now that universe evidence is available.

## Next Work

Continue with the open tasks in:

```text
docs/factor_smoke_experiment_backlog.md
```

Required next item:

1. `FSM-018`: record the final keep/watch/reject decision.

The larger universe is a breadth/generalization test. It should not be used to
change the candidate after seeing results or to rescue weak large-cap evidence.
