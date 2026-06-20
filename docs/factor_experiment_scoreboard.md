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
| TBD | bucket_only | large_cap_fixed | fixed large-cap smoke list | price_behavior | TBD | TBD | future_21d_return | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | watch | Template row; replace after first reviewed run. | TBD | TBD | TBD |

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
