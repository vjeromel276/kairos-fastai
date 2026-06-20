"""Point-in-time fundamental quality features for multi-factor experiments.

Policy:
- Prefer SF1 `datekey` as the filing/availability date.
- If `datekey` is unavailable, use `reportperiod` or `calendardate` plus a
  conservative reporting lag.
- When `lastupdated` is present and enabled, do not use a row until
  `lastupdated <= prediction date`.
"""

from __future__ import annotations

import pandas as pd


DEFAULT_DIMENSION_FILTER = ("MRT",)
DEFAULT_FALLBACK_LAG_DAYS = 90
DEFAULT_GROWTH_PERIODS = 4
QUALITY_FEATURE_COLUMNS = (
    "qual_gross_margin",
    "qual_operating_margin",
    "qual_net_margin",
    "qual_roa",
    "qual_roe",
    "qual_roic",
    "qual_revenue_growth",
    "qual_earnings_growth",
    "qual_debt_to_assets",
)


def numeric_or_nan(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(float("nan"), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def first_numeric(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    result = pd.Series(float("nan"), index=df.index, dtype="float64")
    for column in columns:
        if column in df.columns:
            result = result.combine_first(pd.to_numeric(df[column], errors="coerce"))
    return result


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.where(denominator != 0)


def fundamental_availability_dates(
    fundamentals: pd.DataFrame,
    datekey_column: str = "datekey",
    fallback_date_columns: tuple[str, ...] = ("reportperiod", "calendardate"),
    fallback_lag_days: int = DEFAULT_FALLBACK_LAG_DAYS,
    lastupdated_column: str = "lastupdated",
    enforce_lastupdated: bool = True,
) -> pd.Series:
    """Return conservative availability dates for SF1-style rows."""
    if fallback_lag_days < 0:
        raise ValueError("fallback_lag_days must be >= 0")

    if datekey_column in fundamentals.columns:
        base_date = pd.to_datetime(fundamentals[datekey_column], errors="coerce")
    else:
        base_date = None
        for column in fallback_date_columns:
            if column in fundamentals.columns:
                base_date = (
                    pd.to_datetime(fundamentals[column], errors="coerce")
                    + pd.Timedelta(days=fallback_lag_days)
                )
                break
        if base_date is None:
            raise KeyError(
                "fundamentals require datekey or a fallback report date column"
            )

    if enforce_lastupdated and lastupdated_column in fundamentals.columns:
        lastupdated = pd.to_datetime(
            fundamentals[lastupdated_column],
            errors="coerce",
        )
        return pd.concat([base_date, lastupdated], axis=1).max(axis=1)
    return base_date


def build_fundamental_quality_feature_rows(
    fundamentals: pd.DataFrame,
    ticker_column: str = "ticker",
    dimension_column: str = "dimension",
    dimension_filter: tuple[str, ...] | None = DEFAULT_DIMENSION_FILTER,
    datekey_column: str = "datekey",
    fallback_date_columns: tuple[str, ...] = ("reportperiod", "calendardate"),
    fallback_lag_days: int = DEFAULT_FALLBACK_LAG_DAYS,
    lastupdated_column: str = "lastupdated",
    enforce_lastupdated: bool = True,
    growth_periods: int = DEFAULT_GROWTH_PERIODS,
) -> pd.DataFrame:
    """Return one row per fundamental report with quality features and availability."""
    if ticker_column not in fundamentals.columns:
        raise KeyError(f"missing fundamentals ticker column: {ticker_column}")
    if growth_periods < 1:
        raise ValueError("growth_periods must be >= 1")

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

    revenue = first_numeric(result, ("revenueusd", "revenue"))
    gross_profit = numeric_or_nan(result, "gp")
    ebit = numeric_or_nan(result, "ebit")
    net_income = numeric_or_nan(result, "netinc")
    assets = numeric_or_nan(result, "assets")
    equity = numeric_or_nan(result, "equity")
    debt = first_numeric(result, ("debt", "liabilities"))

    result["qual_gross_margin"] = first_numeric(
        result,
        ("grossmargin",),
    ).combine_first(safe_divide(gross_profit, revenue))
    result["qual_operating_margin"] = first_numeric(
        result,
        ("opmargin",),
    ).combine_first(safe_divide(ebit, revenue))
    result["qual_net_margin"] = first_numeric(
        result,
        ("netmargin",),
    ).combine_first(safe_divide(net_income, revenue))
    result["qual_roa"] = first_numeric(result, ("roa",)).combine_first(
        safe_divide(net_income, assets)
    )
    result["qual_roe"] = first_numeric(result, ("roe",)).combine_first(
        safe_divide(net_income, equity)
    )
    result["qual_roic"] = first_numeric(result, ("roic",))
    result["qual_debt_to_assets"] = safe_divide(debt, assets)

    result["__revenue"] = revenue
    result["__earnings"] = net_income
    sort_date_column = next(
        (
            column
            for column in ("reportperiod", "calendardate", datekey_column)
            if column in result.columns
        ),
        "__available_date",
    )
    result["__sort_date"] = pd.to_datetime(result[sort_date_column], errors="coerce")
    sort_columns = [ticker_column, "__sort_date", "__available_date"]
    group_columns = [ticker_column]
    if dimension_column in result.columns:
        sort_columns.insert(1, dimension_column)
        group_columns.append(dimension_column)
    result = result.sort_values(sort_columns)
    result["qual_revenue_growth"] = result.groupby(group_columns, dropna=False)[
        "__revenue"
    ].pct_change(growth_periods, fill_method=None)
    result["qual_earnings_growth"] = result.groupby(group_columns, dropna=False)[
        "__earnings"
    ].pct_change(growth_periods, fill_method=None)
    result[["qual_revenue_growth", "qual_earnings_growth"]] = result[
        ["qual_revenue_growth", "qual_earnings_growth"]
    ].replace([float("inf"), float("-inf")], pd.NA)

    columns = [ticker_column, "__available_date", *QUALITY_FEATURE_COLUMNS]
    return result[columns].dropna(subset=[ticker_column, "__available_date"])


def add_fundamental_quality_features(
    panel: pd.DataFrame,
    fundamentals: pd.DataFrame,
    ticker_column: str = "ticker",
    date_column: str = "date",
    dimension_column: str = "dimension",
    dimension_filter: tuple[str, ...] | None = DEFAULT_DIMENSION_FILTER,
    datekey_column: str = "datekey",
    fallback_date_columns: tuple[str, ...] = ("reportperiod", "calendardate"),
    fallback_lag_days: int = DEFAULT_FALLBACK_LAG_DAYS,
    lastupdated_column: str = "lastupdated",
    enforce_lastupdated: bool = True,
    growth_periods: int = DEFAULT_GROWTH_PERIODS,
) -> pd.DataFrame:
    """Join point-in-time safe fundamental quality features onto a panel."""
    if ticker_column not in panel.columns:
        raise KeyError(f"missing panel ticker column: {ticker_column}")
    if date_column not in panel.columns:
        raise KeyError(f"missing panel date column: {date_column}")

    feature_rows = build_fundamental_quality_feature_rows(
        fundamentals,
        ticker_column=ticker_column,
        dimension_column=dimension_column,
        dimension_filter=dimension_filter,
        datekey_column=datekey_column,
        fallback_date_columns=fallback_date_columns,
        fallback_lag_days=fallback_lag_days,
        lastupdated_column=lastupdated_column,
        enforce_lastupdated=enforce_lastupdated,
        growth_periods=growth_periods,
    )

    panel_copy = panel.copy()
    panel_copy["__panel_date"] = pd.to_datetime(panel_copy[date_column], errors="coerce")
    panel_copy = panel_copy.sort_values([ticker_column, "__panel_date"])
    feature_rows = feature_rows.sort_values([ticker_column, "__available_date"])

    parts = []
    grouped_features = {
        ticker: group.drop(columns=[ticker_column]).sort_values("__available_date")
        for ticker, group in feature_rows.groupby(ticker_column, sort=False)
    }
    for ticker, group in panel_copy.groupby(ticker_column, sort=False):
        right = grouped_features.get(ticker)
        if right is None or right.empty:
            merged = group.copy()
            for column in QUALITY_FEATURE_COLUMNS:
                merged[column] = pd.Series(
                    float("nan"),
                    index=merged.index,
                    dtype="float64",
                )
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
        return panel.copy()

    result = pd.concat(parts, ignore_index=True).sort_values(
        [ticker_column, date_column],
    )
    drop_columns = [
        column
        for column in ("__panel_date", "__available_date")
        if column in result.columns
    ]
    return result.drop(columns=drop_columns).reset_index(drop=True)
