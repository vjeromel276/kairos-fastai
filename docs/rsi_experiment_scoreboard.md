# RSI Experiment Scoreboard

Use this scoreboard to record compact results after each RSI experiment run.
Do not commit large prediction files; put those under ignored local artifact
paths and reference the path in `metrics_path` when useful.

`scope` must be one of:

- `one_ticker`: a single-symbol plumbing or signal test.
- `panel`: a multi-ticker experiment with date-level ranking metrics.

`keep` should be `yes`, `no`, or `watch`. A feature set earns `yes` only when
validation and test results beat the relevant baseline out of sample.

| experiment_id | scope | ticker_set | feature_set | model | target | train_window | validation_window | test_window | validation_metric_summary | test_metric_summary | keep | decision_notes | metrics_path | commit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TBD | one_ticker | AAPL | A | linear_regression | future_5d_return | TBD | TBD | TBD | TBD | TBD | watch | Initial template row; replace after first run. | TBD | TBD |
