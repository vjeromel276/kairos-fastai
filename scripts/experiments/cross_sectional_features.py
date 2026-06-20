"""Cross-sectional context features for multi-factor experiments."""

from __future__ import annotations

import pandas as pd


DEFAULT_WINSOR_LIMITS = (0.01, 0.99)


def require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise KeyError(f"missing required columns: {', '.join(missing)}")


def winsorized_zscore(
    series: pd.Series,
    winsor_limits: tuple[float, float] = DEFAULT_WINSOR_LIMITS,
) -> pd.Series:
    """Return a within-group winsorized z-score."""
    lower, upper = winsor_limits
    if not 0 <= lower <= upper <= 1:
        raise ValueError("winsor_limits must satisfy 0 <= lower <= upper <= 1")

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0:
        return pd.Series(float("nan"), index=series.index, dtype="float64")

    clipped = numeric.clip(
        lower=numeric.quantile(lower),
        upper=numeric.quantile(upper),
    )
    std = clipped.std(ddof=0)
    if pd.isna(std) or std == 0:
        zscore = pd.Series(float("nan"), index=series.index, dtype="float64")
        zscore.loc[clipped.notna()] = 0.0
        return zscore
    return (clipped - clipped.mean()) / std


def add_cross_sectional_rank_features(
    panel: pd.DataFrame,
    columns: list[str],
    date_column: str = "date",
) -> pd.DataFrame:
    """Add percentile-rank features calculated independently for each date."""
    require_columns(panel, [date_column] + columns)
    result = panel.copy()
    for column in columns:
        result[f"xs_{column}_rank"] = result.groupby(date_column)[column].rank(
            pct=True,
            method="average",
        )
    return result


def add_cross_sectional_zscore_features(
    panel: pd.DataFrame,
    columns: list[str],
    date_column: str = "date",
    winsor_limits: tuple[float, float] = DEFAULT_WINSOR_LIMITS,
) -> pd.DataFrame:
    """Add date-local winsorized z-score features."""
    require_columns(panel, [date_column] + columns)
    result = panel.copy()
    for column in columns:
        result[f"xs_{column}_z"] = result.groupby(date_column)[column].transform(
            lambda series: winsorized_zscore(series, winsor_limits=winsor_limits)
        )
    return result


def add_market_relative_features(
    panel: pd.DataFrame,
    market_proxy: pd.DataFrame,
    columns: list[str],
    date_column: str = "date",
    market_suffix: str = "spy",
) -> pd.DataFrame:
    """
    Add exact-date market-relative features.

    No forward fill is performed. If the market proxy is missing for a date, the
    relative feature is null for that date.
    """
    require_columns(panel, [date_column] + columns)
    require_columns(market_proxy, [date_column] + columns)

    proxy_columns = {
        column: f"__{market_suffix}_{column}"
        for column in columns
    }
    proxy = market_proxy[[date_column] + columns].rename(columns=proxy_columns)
    result = panel.merge(proxy, on=date_column, how="left")
    for column in columns:
        proxy_column = proxy_columns[column]
        result[f"xs_{column}_minus_{market_suffix}"] = result[column] - result[proxy_column]
    return result.drop(columns=list(proxy_columns.values()))


def add_sector_relative_features(
    panel: pd.DataFrame,
    columns: list[str],
    date_column: str = "date",
    sector_column: str = "sector",
) -> pd.DataFrame:
    """Add sector-relative features when sector data is available."""
    require_columns(panel, [date_column] + columns)
    result = panel.copy()
    if sector_column not in result.columns:
        for column in columns:
            result[f"xs_{column}_minus_sector"] = pd.Series(
                float("nan"),
                index=result.index,
                dtype="float64",
            )
        return result

    for column in columns:
        sector_mean = result.groupby([date_column, sector_column], dropna=False)[
            column
        ].transform("mean")
        result[f"xs_{column}_minus_sector"] = result[column] - sector_mean
    return result


def add_cross_sectional_context_features(
    panel: pd.DataFrame,
    rank_columns: list[str],
    zscore_columns: list[str] | None = None,
    market_relative_columns: list[str] | None = None,
    sector_relative_columns: list[str] | None = None,
    market_proxy: pd.DataFrame | None = None,
    date_column: str = "date",
    sector_column: str = "sector",
    winsor_limits: tuple[float, float] = DEFAULT_WINSOR_LIMITS,
) -> pd.DataFrame:
    """Add the configured cross-sectional context feature families."""
    result = add_cross_sectional_rank_features(
        panel,
        columns=rank_columns,
        date_column=date_column,
    )
    if zscore_columns:
        result = add_cross_sectional_zscore_features(
            result,
            columns=zscore_columns,
            date_column=date_column,
            winsor_limits=winsor_limits,
        )
    if sector_relative_columns:
        result = add_sector_relative_features(
            result,
            columns=sector_relative_columns,
            date_column=date_column,
            sector_column=sector_column,
        )
    if market_relative_columns:
        if market_proxy is None:
            raise ValueError("market_proxy is required for market-relative features")
        result = add_market_relative_features(
            result,
            market_proxy=market_proxy,
            columns=market_relative_columns,
            date_column=date_column,
        )
    return result
