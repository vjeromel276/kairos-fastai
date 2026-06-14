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
| RSI-015-A-reg | one_ticker | AAPL | A | linear_regression | future_5d_return | 2015-01-02..2021-12-31 | 2022-04-04..2023-12-29 | 2024-04-03..2026-06-05 | RMSE 0.0383, IC 0.0274 | RMSE 0.0407, IC -0.0915 | no | Worse than the test mean-return baseline RMSE 0.0405. | local `/tmp/aapl_rsi_abc_20260612.json` | RSI-015 |
| RSI-015-A-cls | one_ticker | AAPL | A | logistic_regression | winner_5d | 2015-01-02..2021-12-31 | 2022-04-04..2023-12-29 | 2024-04-03..2026-06-05 | AUC 0.5766, accuracy 0.5411 | AUC 0.4787, accuracy 0.5683 | no | Validation AUC did not carry to test and test accuracy trailed the always-up baseline 0.5738. | local `/tmp/aapl_rsi_abc_20260612.json` | RSI-015 |
| RSI-015-B-reg | one_ticker | AAPL | B | linear_regression | future_5d_return | 2015-01-02..2021-12-31 | 2022-04-04..2023-12-29 | 2024-04-03..2026-06-05 | RMSE 0.0383, IC 0.0822 | RMSE 0.0408, IC -0.0066 | no | Slope features improved validation IC but not test RMSE. | local `/tmp/aapl_rsi_abc_20260612.json` | RSI-015 |
| RSI-015-B-cls | one_ticker | AAPL | B | logistic_regression | winner_5d | 2015-01-02..2021-12-31 | 2022-04-04..2023-12-29 | 2024-04-03..2026-06-05 | AUC 0.5891, accuracy 0.5571 | AUC 0.5098, accuracy 0.5812 | watch | Only feature set with a positive test AUC and small accuracy edge over always-up; too small for model D justification. | local `/tmp/aapl_rsi_abc_20260612.json` | RSI-015 |
| RSI-015-C-reg | one_ticker | AAPL | C | linear_regression | future_5d_return | 2015-01-02..2021-12-31 | 2022-04-04..2023-12-29 | 2024-04-03..2026-06-05 | RMSE 0.0382, IC 0.0917 | RMSE 0.0409, IC -0.0282 | no | Best validation RMSE, but worse than the test mean-return baseline. | local `/tmp/aapl_rsi_abc_20260612.json` | RSI-015 |
| RSI-015-C-cls | one_ticker | AAPL | C | logistic_regression | winner_5d | 2015-01-02..2021-12-31 | 2022-04-04..2023-12-29 | 2024-04-03..2026-06-05 | AUC 0.5912, accuracy 0.5525 | AUC 0.4893, accuracy 0.5756 | no | Best validation AUC, but test AUC fell below 0.5. | local `/tmp/aapl_rsi_abc_20260612.json` | RSI-015 |

## RSI Sequence Model D Decision

Decision: defer the 20-day RSI sequence model.

Evidence came from a one-ticker AAPL run against local `sep_base` rows through
2026-06-12. The run used 7,152 source rows, a 5-trading-day forward return
target, and a 63-trading-day embargo between train, validation, and test
windows.

The tabular recency features are not strong enough yet to justify a sequence
model. Feature set C had the best validation regression RMSE and classification
AUC, but both weakened on the test window. Feature set B produced the only
positive test classification AUC, but the margin was small: AUC 0.5098 and
accuracy 0.5812 versus the always-up baseline accuracy 0.5738. Regression test
RMSE for A, B, and C all trailed the mean-return baseline.

Next atomic task before any sequence model work: run the tested panel evaluation
on a representative ticker set and require the tabular RSI features to show a
stable out-of-sample ranking or classification edge across dates. Do not start
sequence tensor or neural-network code until that panel evidence exists.
