"""Prune kairos-fastai.duckdb down to source/reference tables only.

This script intentionally operates on the cloned fastai DB, not the original
kairos-flow.duckdb. It drops old feature tables, model outputs, backtests,
portfolio outputs, stale teacher artifacts, and any other derived objects.

Usage:
    python scripts/fastai_reset/prune_to_source_tables.py \
        --db data/kairos-fastai.duckdb
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


KEEP_TABLES = {
    # Current canonical raw/source tables
    "sep_base",
    "daily",
    "sf1",
    "sf2",
    "sfp",
    "sf3",
    "sf3a",
    "sf3b",
    "tickers",

    # SHARADAR reference/source tables
    "sharadar_actions",
    "sharadar_events",
    "sharadar_metrics",
    "sharadar_sp500",
    "sharadar_indicators",

    # Core calendar reference
    "trading_calendar",
}


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.db.exists():
        raise FileNotFoundError(args.db)

    if args.db.name == "kairos-flow.duckdb":
        raise RuntimeError("Refusing to prune the original kairos-flow.duckdb.")

    con = duckdb.connect(str(args.db))

    objects = con.execute("""
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_type, table_name
    """).fetchall()

    to_drop = [
        (name, table_type)
        for name, table_type in objects
        if name not in KEEP_TABLES
    ]

    print(f"Database: {args.db}")
    print(f"Objects found: {len(objects)}")
    print(f"Objects kept: {len(objects) - len(to_drop)}")
    print(f"Objects to drop: {len(to_drop)}")

    print("\nKeeping:")
    for table in sorted(KEEP_TABLES):
        exists = any(name == table for name, _ in objects)
        print(f"  {'✓' if exists else 'MISSING'} {table}")

    print("\nDropping:")
    for name, table_type in to_drop:
        print(f"  {table_type:10s} {name}")

    if args.dry_run:
        print("\nDry run only. No changes made.")
        return

    # Drop views first, then tables.
    for name, table_type in to_drop:
        if table_type == "VIEW":
            con.execute(f"DROP VIEW IF EXISTS {quote_ident(name)}")

    for name, table_type in to_drop:
        if table_type == "BASE TABLE":
            con.execute(f"DROP TABLE IF EXISTS {quote_ident(name)}")

    con.execute("CHECKPOINT")

    remaining = con.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
    """).fetchdf()

    print("\nRemaining objects:")
    print(remaining.to_string(index=False))


if __name__ == "__main__":
    main()
