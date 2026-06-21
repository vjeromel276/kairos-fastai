# Factor Experiment Scoreboard

Use this scoreboard to record compact results from multi-factor bucket and
stack experiments. Keep large metrics files, predictions, model artifacts, and
CSV exports out of Git; record their local artifact paths instead.

`run_type` must be one of:

- `bucket_only`: one feature bucket tested alone.
- `cumulative`: an ordered bucket stack where a bucket is added to prior
  accepted buckets.
- `final_combined`: a candidate full-stack model evaluated for promotion.

`panel_name` must identify whether results came from `large_cap_fixed`,
`universe_fastai_v1`, or another reviewed panel.

`keep` should be `yes`, `no`, or `watch`. A stack earns `yes` only when test
and walk-forward evidence beat the relevant baseline after turnover,
transaction-cost, and liquidity/capacity checks.

| experiment_id | run_type | panel_name | ticker_set | bucket_stack | feature_count | model | target | train_window | validation_window | test_window | embargo | validation_metric_summary | test_metric_summary | turnover_summary | cost_adjusted_summary | liquidity_summary | keep | decision_notes | metrics_path | artifact_path | commit |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FSM-012-price-regime | cumulative | large_cap_fixed | fixed large-cap smoke list, 20 tickers | price_behavior + regime_context | 21 | ridge_regression | future_21d_return | 1997-12-31..2021-12-31 | 2022-02-02..2023-12-29 | 2024-02-01..2026-05-19 scored | 21 trading days | top-5 return 0.0264, win 0.5996, IC 0.1402 | top-5 return 0.0246, win 0.6080, IC 0.0685 | avg turnover 0.1345, holding overlap 0.8655 | gross 0.0254, cost-adjusted 0.0253 at 10 bps | selected min ADV20 365M, median 4.43B | watch | Positive fixed-split smoke evidence with low turnover, strong liquidity, and computed sector diagnostics; keep under watch because fundamental quality lacks long-split PIT coverage, full-stack walk-forward is not yet complete, and this is not universe-wide evidence. | docs/factor_smoke_cumulative_ablations.md; docs/factor_smoke_neutrality_diagnostics.md; docs/factor_smoke_turnover_capacity.md; docs/factor_smoke_walk_forward_evaluation.md | local_artifacts/factor_smoke_v1/fsb001_walk_forward_report.json; local_artifacts/factor_smoke_v1/fsb006_neutrality_report.json; local_artifacts/factor_smoke_v1/fsb006_turnover_capacity_report.json; DuckDB table factor_smoke_scores_v1 | FSM-012 |
| FSM-017-price-regime-universe | final_combined | universe_fastai_v1 | reviewed universe, 6,424 scored-panel tickers | price_behavior + regime_context | 21 | ridge_regression | future_21d_return | 2018-01-02..2021-12-31 | 2022-02-02..2023-12-29 | 2024-02-01..2026-05-19 scored | 21 trading days | top-5 return -0.0219, win 0.3983, IC 0.0396 | top-5 return -0.0136, win 0.4318, IC 0.0260 | validation avg turnover 0.2672; test avg turnover 0.2084 | validation cost-adjusted -0.0221; test cost-adjusted -0.0138 at 10 bps | selected min ADV20 0.90M, median test ADV20 10.70M | no | Universe generalization failed: model beats a weak prior-return baseline but validation and test top-5 returns are negative, beta-adjusted returns are negative, validation sector-neutral return is negative, and top selections are concentrated. | docs/factor_universe_price_regime_generalization.md; docs/factor_smoke_full_stack_walk_forward.md | local_artifacts/factor_smoke_v1/fsm017_universe_score_export_report.json; local_artifacts/factor_smoke_v1/fsm017_universe_neutrality_report.json; local_artifacts/factor_smoke_v1/fsm017_universe_turnover_capacity_report.json; DuckDB table factor_universe_price_regime_scores_v1 | FSM-017 |

## Promotion Notes

Promotion-quality evidence requires:

- adjusted forward returns
- explicit panel name
- validation and test date windows
- walk-forward evidence when available
- top-K ranking metrics
- turnover proxy
- transaction-cost proxy
- selected-name liquidity/capacity summary
- source freshness status or explicit skip reason

Large-cap smoke results can prove plumbing and basic sanity, but they should not
be used alone to promote a feature stack.
