# Price-Regime Promotion Criteria

Decision date: 2026-06-20

## Purpose

This document freezes the next factor candidate before running the next
diagnostics. New evidence should be evaluated against this contract rather than
changing the candidate or criteria after results are known.

## Frozen Candidate

Candidate stack:

```text
price_behavior + regime_context
```

Model:

```text
ridge_regression
```

Primary target:

```text
future_21d_return
```

Ranking objective:

```text
daily top-5 by prediction_score
```

Baseline:

```text
prior_21d_return
```

Embargo:

```text
21 trading days
```

Transaction-cost proxy:

```text
10 bps per unit turnover
```

Model features are limited to the frozen candidate stack. Panel builds may
include non-model diagnostic columns such as `liq_adv_20d`, `risk_beta_spy_21d`,
`sector`, and `industry` so neutrality, turnover, capacity, and concentration
checks can run.

## Fixed Split Policy

Large-cap smoke fixed split:

| split | date policy |
| --- | --- |
| train | through 2021-12-31 |
| validation | 2022-02-02 through 2023-12-29 |
| test | 2024-02-01 through latest scored date available after target horizon |

The same target, embargo, top-K, and diagnostic metrics must be used for
`universe_fastai_v1` unless a later backlog item explicitly freezes a new
version of this criteria document before any universe results are reviewed.

## Walk-Forward Policy

Large-cap full-stack walk-forward should use the established smoke fold shape
unless the command is versioned before running:

| parameter | value |
| --- | ---: |
| train size | 756 trading rows |
| validation size | 252 trading rows |
| test size | 252 trading rows |
| step size | 252 trading rows |
| embargo | 21 trading rows |
| top-K | 5 |

The walk-forward report must evaluate the combined frozen stack, not only
bucket-only models.

## Required Diagnostics

Every promotion decision must include:

- validation and test top-K average return
- validation and test top-K win rate
- validation and test information coefficient
- prior-return baseline comparison
- beta-adjusted ranking result when `risk_beta_spy_21d` is available
- sector-neutral ranking result when `sector` is available
- top-K sector concentration
- turnover and holding overlap
- 10 bps cost-adjusted top-K return
- selected-name liquidity using `liq_adv_20d`
- source freshness or explicit freshness skip reason

## Stop Or Continue Rules

Move from the large-cap smoke panel to `universe_fastai_v1` only if the
full-stack large-cap walk-forward result avoids hard failure:

- aggregate validation and test top-K average returns are positive
- aggregate test IC is not negative
- test cost-adjusted top-K average return remains positive
- selected-name liquidity is not missing for the selected rows
- sector concentration is computed or has an explicit source skip reason

If any hard failure appears, stop and record `watch` or `reject` before running
the universe test.

## Universe Generalization Test

`universe_fastai_v1` is a generalization test. It is not a way to rescue a weak
large-cap result.

The universe run must use the same frozen candidate stack, model, target,
embargo, top-K, and diagnostics. The result should answer whether the signal
survives a broader stock universe with more names, more sector breadth, and
more liquidity variation.

## Decision Rules

`keep` requires all of the following:

- validation and test top-K average returns are positive
- validation and test top-K average returns beat the prior-return baseline
- validation and test IC are non-negative
- walk-forward aggregate validation and test results are positive
- universe validation and test results remain positive after costs
- beta-adjusted and sector-neutral results do not erase the signal
- average turnover does not make cost-adjusted return materially weaker than
  gross return
- selected-name liquidity is sufficient for the universe being tested
- no single sector dominates top-K selections enough to explain the result by
  one concentrated sector bet

`watch` is appropriate when the signal is positive but one or more promotion
risks remain, such as weak universe evidence, weak IC, high concentration,
short recent-only coverage, or incomplete diagnostics.

`reject` is appropriate when the frozen candidate fails out-of-sample test
metrics, fails walk-forward stability, fails after costs, or fails to
generalize beyond the large-cap smoke panel.

## Current State

Current status:

```text
watch
```

Reason:

The fixed large-cap split is positive and the FSB blockers are resolved, but
the frozen stack still needs full-stack walk-forward evidence and
`universe_fastai_v1` generalization evidence before it can be promoted.
