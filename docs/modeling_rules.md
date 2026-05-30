# Modeling Rules

## Time Series Rules
- Never use random train/test splits.
- Use trading-day aware windows.
- Prevent leakage from future rows.

## Reproducibility
- All experiments must log:
  - seed
  - parameters
  - metrics
  - artifact paths

## Validation
- Validation dates must be later than training dates.