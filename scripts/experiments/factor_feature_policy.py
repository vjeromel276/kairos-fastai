"""Reviewed feature availability policy for factor experiments."""

from __future__ import annotations


OPTIONAL_FEATURES_BY_BUCKET = {
    # Turnover depends on share-count or market-cap inputs that may be absent in
    # a smoke panel. It should not suppress the rest of the liquidity bucket.
    "volume_liquidity": {"liq_turnover"},
    # The valuation policy documents cash-flow yield as optional because it
    # combines daily valuation data with PIT fundamentals.
    "valuation": {"val_fcf_yield"},
}


def optional_features_for_bucket(bucket: str) -> set[str]:
    return set(OPTIONAL_FEATURES_BY_BUCKET.get(bucket, set()))
