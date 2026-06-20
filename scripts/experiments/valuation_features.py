"""Valuation features for multi-factor experiments.

Daily valuation ratios are joined on the exact prediction date. Optional SF1
cash-flow numerators use the same point-in-time policy as MFF-012.
"""

from __future__ import annotations

import pandas as pd

from scripts.experiments.fundamental_quality_features import (
    DEFAULT_DIMENSION_FILTER,
    DEFAULT_FALLBACK_LAG_DAYS,
    fundamental_availability_dates,
    numeric_or_nan,
    safe_divide,
)


DEFAULT_CAP_BOUNDS = (-10.0, 10.0)
VALUATION_FEATURE_COLUMNS = (
    "val_earnings_yield",
    "val_sales_yield",
    "val_book_yield",
    "val_ebit_ev_yield",
    "val_ebitda_ev_yield",
    "val_fcf_yield",
)


def validate_cap_bounds(cap_bounds: tuple[float, float] | None) -> tuple[float, float] | None:
    if cap_bounds is None:
        return None
    lower, upper = cap_bounds
    if lower > upper:
        raise ValueError("cap_bounds must satisfy lower <= upper")
    return lower, upper


def cap_extreme_values(
    series: pd.Series,
    cap_bounds: tuple[float, float] | None = DEFAULT_CAP_BOUNDS,
) -> pd.Series:
    bounds = validate_cap_bounds(cap_bounds)
    numeric = pd.to_numeric(series, errors="coerce")
    if bounds is None:
        return numeric
    lower, upper = bounds
    return numeric.clip(lower=lower, upper=upper)


def safe_inverse(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return 1.0 / numeric.where(numeric != 0)


def require_columns(df: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise KeyError(f"{label} missing required columns: {', '.join(missing)}")


def daily_valuation_inputs(
    daily: pd.DataFrame,
    ticker_column: str,
    date_column: str,
) -> pd.DataFrame:
    require_columns(daily, (ticker_column, date_column), "daily")
    input_columns = [
        column
        for column in ("pe", "ps", "pb", "evebit", "evebitda", "marketcap")
        if column in daily.columns
    ]
    result = daily[[ticker_column, date_column, *input_columns]].copy()
    result["__daily_date"] = pd.to_datetime(result[date_column], errors="coerce")
    rename_map = {column: f"__daily_{column}" for column in input_columns}
    return (
        result.rename(columns=rename_map)
        .sort_values([ticker_column, "__daily_date"])
        .drop_duplicates(subset=[ticker_column, "__daily_date"], keep="last")
    )


def build_valuation_fundamental_rows(
    fundamentals: pd.DataFrame,
    ticker_column: str = "ticker",
    dimension_column: str = "dimension",
    dimension_filter: tuple[str, ...] | None = DEFAULT_DIMENSION_FILTER,
    datekey_column: str = "datekey",
    fallback_date_columns: tuple[str, ...] = ("reportperiod", "calendardate"),
    fallback_lag_days: int = DEFAULT_FALLBACK_LAG_DAYS,
    lastupdated_column: str = "lastupdated",
    enforce_lastupdated: bool = True,
    cash_flow_column: str = "fcf",
) -> pd.DataFrame:
    """Return point-in-time cash-flow rows for valuation features."""
    if ticker_column not in fundamentals.columns:
        raise KeyError(f"missing fundamentals ticker column: {ticker_column}")

    result = fundamentals.copy()
    if (
        dimension_filter is not None
        and dimension_column in result.columns
        and len(dimension_filter) > 0
    ):
        result = result[result[dimension_column].isin(dimension_filter)].copy()

    result["__available_date"] = fundamental_availability_dates(
        result,
        datekey_column=datekey_column,
        fallback_date_columns=fallback_date_columns,
        fallback_lag_days=fallback_lag_days,
        lastupdated_column=lastupdated_column,
        enforce_lastupdated=enforce_lastupdated,
    )
    result["__fcf"] = numeric_or_nan(result, cash_flow_column)
    return result[[ticker_column, "__available_date", "__fcf"]].dropna(
        subset=[ticker_column, "__available_date"]
    )


def join_fundamental_cash_flow(
    panel: pd.DataFrame,
    fundamentals: pd.DataFrame,
    ticker_column: str,
    date_column: str,
    **kwargs: object,
) -> pd.DataFrame:
    feature_rows = build_valuation_fundamental_rows(
        fundamentals,
        ticker_column=ticker_column,
        **kwargs,
    ).sort_values([ticker_column, "__available_date"])
    panel_copy = panel.copy()
    panel_copy["__panel_date"] = pd.to_datetime(panel_copy[date_column], errors="coerce")
    panel_copy = panel_copy.sort_values([ticker_column, "__panel_date"])

    parts = []
    grouped_features = {
        ticker: group.drop(columns=[ticker_column]).sort_values("__available_date")
        for ticker, group in feature_rows.groupby(ticker_column, sort=False)
    }
    for ticker, group in panel_copy.groupby(ticker_column, sort=False):
        right = grouped_features.get(ticker)
        if right is None or right.empty:
            merged = group.copy()
            merged["__fcf"] = pd.Series(float("nan"), index=merged.index, dtype="float64")
        else:
            merged = pd.merge_asof(
                group.sort_values("__panel_date"),
                right,
                left_on="__panel_date",
                right_on="__available_date",
                direction="backward",
            )
        parts.append(merged)

    if not parts:
        panel_copy["__fcf"] = pd.Series(float("nan"), index=panel_copy.index)
        return panel_copy
    return pd.concat(parts, ignore_index=True)


def add_valuation_features(
    panel: pd.DataFrame,
    daily: pd.DataFrame,
    fundamentals: pd.DataFrame | None = None,
    ticker_column: str = "ticker",
    date_column: str = "date",
    cap_bounds: tuple[float, float] | None = DEFAULT_CAP_BOUNDS,
    dimension_column: str = "dimension",
    dimension_filter: tuple[str, ...] | None = DEFAULT_DIMENSION_FILTER,
    datekey_column: str = "datekey",
    fallback_date_columns: tuple[str, ...] = ("reportperiod", "calendardate"),
    fallback_lag_days: int = DEFAULT_FALLBACK_LAG_DAYS,
    lastupdated_column: str = "lastupdated",
    enforce_lastupdated: bool = True,
    cash_flow_column: str = "fcf",
) -> pd.DataFrame:
    """Join daily valuation features and optional PIT cash-flow yield."""
    require_columns(panel, (ticker_column, date_column), "panel")
    validate_cap_bounds(cap_bounds)

    result = panel.copy()
    result["__panel_date"] = pd.to_datetime(result[date_column], errors="coerce")
    daily_inputs = daily_valuation_inputs(daily, ticker_column, date_column)
    result = result.merge(
        daily_inputs.drop(columns=[date_column]),
        left_on=[ticker_column, "__panel_date"],
        right_on=[ticker_column, "__daily_date"],
        how="left",
    )

    result["val_earnings_yield"] = cap_extreme_values(
        safe_inverse(numeric_or_nan(result, "__daily_pe")),
        cap_bounds,
    )
    result["val_sales_yield"] = cap_extreme_values(
        safe_inverse(numeric_or_nan(result, "__daily_ps")),
        cap_bounds,
    )
    result["val_book_yield"] = cap_extreme_values(
        safe_inverse(numeric_or_nan(result, "__daily_pb")),
        cap_bounds,
    )
    result["val_ebit_ev_yield"] = cap_extreme_values(
        safe_inverse(numeric_or_nan(result, "__daily_evebit")),
        cap_bounds,
    )
    result["val_ebitda_ev_yield"] = cap_extreme_values(
        safe_inverse(numeric_or_nan(result, "__daily_evebitda")),
        cap_bounds,
    )

    if fundamentals is None:
        result["val_fcf_yield"] = pd.Series(
            float("nan"),
            index=result.index,
            dtype="float64",
        )
    else:
        result = join_fundamental_cash_flow(
            result,
            fundamentals,
            ticker_column=ticker_column,
            date_column=date_column,
            dimension_column=dimension_column,
            dimension_filter=dimension_filter,
            datekey_column=datekey_column,
            fallback_date_columns=fallback_date_columns,
            fallback_lag_days=fallback_lag_days,
            lastupdated_column=lastupdated_column,
            enforce_lastupdated=enforce_lastupdated,
            cash_flow_column=cash_flow_column,
        )
        result["val_fcf_yield"] = cap_extreme_values(
            safe_divide(
                numeric_or_nan(result, "__fcf"),
                numeric_or_nan(result, "__daily_marketcap"),
            ),
            cap_bounds,
        )

    drop_columns = [
        column
        for column in result.columns
        if column.startswith("__daily_") or column in {"__panel_date", "__available_date", "__fcf"}
    ]
    return result.drop(columns=drop_columns).sort_values(
        [ticker_column, date_column],
    ).reset_index(drop=True)
