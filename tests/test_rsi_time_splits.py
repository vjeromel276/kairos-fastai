from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from scripts.experiments.rsi_time_splits import default_embargo, make_time_splits


def daily_frame(days: int) -> pd.DataFrame:
    start = date(2026, 1, 1)
    rows = []
    row_id = 0
    for offset in range(days):
        trading_date = start + timedelta(days=offset)
        for ticker in ("AAPL", "MSFT"):
            rows.append(
                {
                    "row_id": row_id,
                    "ticker": ticker,
                    "date": trading_date,
                }
            )
            row_id += 1
    return pd.DataFrame(rows)


def test_default_embargo_uses_larger_lookback_or_horizon() -> None:
    assert default_embargo(feature_lookback_days=63, prediction_horizon_days=5) == 63
    assert default_embargo(feature_lookback_days=20, prediction_horizon_days=30) == 30


def test_calendar_embargo_excludes_rows_between_windows() -> None:
    df = daily_frame(12)

    splits = make_time_splits(
        df,
        train_end="2026-01-05",
        validation_end="2026-01-09",
        test_end="2026-01-12",
        embargo=2,
        embargo_unit="calendar",
    )

    assert splits["train"]["date"].min() == date(2026, 1, 1)
    assert splits["train"]["date"].max() == date(2026, 1, 5)
    assert set(splits["validation"]["date"]) == {date(2026, 1, 8), date(2026, 1, 9)}
    assert set(splits["test"]["date"]) == {date(2026, 1, 12)}
    assert date(2026, 1, 6) not in set(splits["validation"]["date"])
    assert date(2026, 1, 7) not in set(splits["validation"]["date"])
    assert date(2026, 1, 10) not in set(splits["test"]["date"])
    assert date(2026, 1, 11) not in set(splits["test"]["date"])


def test_trading_row_embargo_excludes_first_n_unique_dates() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["AAPL"] * 7,
            "date": [
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 5),
                date(2026, 1, 8),
                date(2026, 1, 9),
                date(2026, 1, 12),
                date(2026, 1, 13),
            ],
        }
    )

    splits = make_time_splits(
        df,
        train_end="2026-01-02",
        validation_end="2026-01-09",
        test_end="2026-01-13",
        embargo=1,
        embargo_unit="trading",
    )

    assert splits["train"]["date"].tolist() == [date(2026, 1, 1), date(2026, 1, 2)]
    assert splits["validation"]["date"].tolist() == [date(2026, 1, 8), date(2026, 1, 9)]
    assert splits["test"]["date"].tolist() == [date(2026, 1, 13)]


def test_splits_have_no_overlapping_dates_and_preserve_source_order() -> None:
    df = daily_frame(15)

    splits = make_time_splits(
        df,
        train_start="2026-01-02",
        train_end="2026-01-05",
        validation_start="2026-01-06",
        validation_end="2026-01-10",
        test_start="2026-01-11",
        test_end="2026-01-15",
        embargo=1,
        embargo_unit="calendar",
    )

    split_date_sets = [set(split["date"]) for split in splits.values()]
    assert split_date_sets[0].isdisjoint(split_date_sets[1])
    assert split_date_sets[0].isdisjoint(split_date_sets[2])
    assert split_date_sets[1].isdisjoint(split_date_sets[2])
    assert splits["train"]["date"].max() < splits["validation"]["date"].min()
    assert splits["validation"]["date"].max() < splits["test"]["date"].min()

    for split in splits.values():
        assert split["row_id"].tolist() == sorted(split["row_id"].tolist())


def test_invalid_boundaries_raise() -> None:
    df = daily_frame(5)

    with pytest.raises(ValueError, match="train_end < validation_end < test_end"):
        make_time_splits(
            df,
            train_end="2026-01-05",
            validation_end="2026-01-04",
            test_end="2026-01-06",
        )
