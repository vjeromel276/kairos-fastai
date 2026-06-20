from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.experiments.factor_time_splits import (
    default_factor_embargo,
    make_factor_time_splits,
)


def panel_frame(days: int) -> pd.DataFrame:
    start = date(2026, 1, 1)
    rows = []
    row_id = 0
    for offset in range(days):
        trading_date = start + timedelta(days=offset)
        for ticker in ("AAPL", "MSFT", "NVDA"):
            rows.append(
                {
                    "row_id": row_id,
                    "ticker": ticker,
                    "date": trading_date,
                    "future_21d_return": 0.01,
                }
            )
            row_id += 1
    return pd.DataFrame(rows)


def test_default_factor_embargo_uses_252_day_lookback() -> None:
    assert default_factor_embargo() == 252
    assert default_factor_embargo(feature_lookback_days=63, prediction_horizon_days=21) == 63
    assert default_factor_embargo(feature_lookback_days=5, prediction_horizon_days=21) == 21


def test_factor_time_splits_use_global_panel_date_windows() -> None:
    df = panel_frame(10)

    splits = make_factor_time_splits(
        df,
        train_end="2026-01-04",
        validation_end="2026-01-07",
        test_end="2026-01-10",
        embargo=0,
    )

    assert len(splits["train"]) == 12
    assert len(splits["validation"]) == 9
    assert len(splits["test"]) == 9
    assert set(splits["train"]["date"]) == {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
    }
    assert set(splits["validation"]["date"]) == {
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    }
    assert set(splits["test"]["date"]) == {
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 10),
    }

    for split in splits.values():
        assert split["ticker"].nunique() == 3
        assert split["row_id"].tolist() == sorted(split["row_id"].tolist())


def test_factor_trading_embargo_excludes_dates_for_all_tickers() -> None:
    df = panel_frame(10)

    splits = make_factor_time_splits(
        df,
        train_end="2026-01-04",
        validation_end="2026-01-07",
        test_end="2026-01-10",
        embargo=1,
        embargo_unit="trading",
    )

    assert date(2026, 1, 5) not in set(splits["validation"]["date"])
    assert set(splits["validation"]["date"]) == {
        date(2026, 1, 6),
        date(2026, 1, 7),
    }
    assert date(2026, 1, 8) not in set(splits["test"]["date"])
    assert set(splits["test"]["date"]) == {
        date(2026, 1, 9),
        date(2026, 1, 10),
    }


def test_factor_time_splits_reject_random_like_invalid_boundaries() -> None:
    df = panel_frame(5)

    with pytest.raises(ValueError, match="train_end < validation_end < test_end"):
        make_factor_time_splits(
            df,
            train_end="2026-01-04",
            validation_end="2026-01-03",
            test_end="2026-01-05",
        )
