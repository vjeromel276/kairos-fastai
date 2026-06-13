from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


TABLES = [
    "sep_base",
    "daily",
    "sf1",
    "sf2",
    "sfp",
    "sf3",
    "sf3a",
    "sf3b",
    "tickers",
    "sharadar_actions",
    "sharadar_events",
    "sharadar_metrics",
    "sharadar_sp500",
    "sharadar_indicators",
    "trading_calendar",
]


DATE_COLUMNS = {
    "sep_base": "date",
    "daily": "date",
    "sf1": "datekey",
    "sf2": "filingdate",
    "sfp": "date",
    "sf3": "calendardate",
    "sf3a": "calendardate",
    "sf3b": "calendardate",
    "sharadar_actions": "date",
    "sharadar_events": "date",
    "sharadar_metrics": "date",
    "sharadar_sp500": "date",
    "trading_calendar": "trading_date",
}


ENTITY_COLUMNS = {
    "sep_base": "ticker",
    "daily": "ticker",
    "sf1": "ticker",
    "sf2": "ticker",
    "sfp": "ticker",
    "sf3": "ticker",
    "sf3a": "ticker",
    "tickers": "ticker",
    "sharadar_actions": "ticker",
    "sharadar_events": "ticker",
    "sharadar_metrics": "ticker",
    "sharadar_sp500": "ticker",
    "sf3b": "investorname",
}


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    result = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name = ?
        """,
        [table],
    ).fetchone()
    return bool(result and result[0])


def column_exists(con: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    result = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = ?
          AND column_name = ?
        """,
        [table, column],
    ).fetchone()
    return bool(result and result[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)

    rows = []

    for table in TABLES:
        if not table_exists(con, table):
            rows.append(
                {
                    "table_name": table,
                    "exists": False,
                    "rows": None,
                    "min_date": None,
                    "max_date": None,
                    "entity_column": None,
                    "distinct_entities": None,
                }
            )
            continue

        date_col = DATE_COLUMNS.get(table)
        entity_col = ENTITY_COLUMNS.get(table)

        select_parts = ["COUNT(*) AS rows"]

        if date_col and column_exists(con, table, date_col):
            select_parts.append(f"MIN({quote_ident(date_col)}) AS min_date")
            select_parts.append(f"MAX({quote_ident(date_col)}) AS max_date")
        else:
            select_parts.append("NULL AS min_date")
            select_parts.append("NULL AS max_date")

        if entity_col and column_exists(con, table, entity_col):
            select_parts.append(f"COUNT(DISTINCT {quote_ident(entity_col)}) AS distinct_entities")
        else:
            select_parts.append("NULL AS distinct_entities")

        sql = f"""
            SELECT
                {", ".join(select_parts)}
            FROM {quote_ident(table)}
        """

        result = con.execute(sql).fetchone()

        rows.append(
            {
                "table_name": table,
                "exists": True,
                "rows": result[0],
                "min_date": result[1],
                "max_date": result[2],
                "entity_column": entity_col if entity_col and column_exists(con, table, entity_col) else None,
                "distinct_entities": result[3],
            }
        )

    out = pd.DataFrame(rows)
    print(out.to_string(index=False))

    print("\nsep_base duplicate ticker/date keys:")
    print(
        con.execute(
            """
            SELECT COUNT(*) AS duplicate_ticker_date_keys
            FROM (
                SELECT ticker, date, COUNT(*) AS n
                FROM sep_base
                GROUP BY ticker, date
                HAVING COUNT(*) > 1
            )
            """
        )
        .fetchdf()
        .to_string(index=False)
    )

    print("\ndaily duplicate ticker/date keys:")
    print(
        con.execute(
            """
            SELECT COUNT(*) AS duplicate_ticker_date_keys
            FROM (
                SELECT ticker, date, COUNT(*) AS n
                FROM daily
                GROUP BY ticker, date
                HAVING COUNT(*) > 1
            )
            """
        )
        .fetchdf()
        .to_string(index=False)
    )

    print("\nRemaining DB objects:")
    print(
        con.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
            """
        )
        .fetchdf()
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
