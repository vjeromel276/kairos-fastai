# Project Contracts

## CLI Contracts
- Existing CLI flags must remain functional.

## Date Contracts
- Use YYYY-MM-DD everywhere.

## Model Contracts
- Models must save:
  - learner
  - config
  - preprocessing state
  - metrics

## Data Contracts
- Features may not include future information.
- Validation must be time-aware.

## Output Contracts
- Prediction CSV columns:
  - symbol
  - prediction_date
  - score
  - probability