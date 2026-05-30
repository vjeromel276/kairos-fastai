from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FailingSwapConnection:
    def __init__(self, conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
        self._conn = conn
        self._df = df
        self.failed = False

    def execute(self, sql: str, *args, **kwargs):
        df = self._df
        normalized = " ".join(sql.split())
        if (
            not self.failed
            and normalized.startswith(
                "CREATE TABLE tickers AS SELECT * FROM tmp_tickers_replacement_"
            )
        ):
            self.failed = True
            raise RuntimeError("injected swap failure")
        return self._conn.execute(sql, *args, **kwargs)


def test_replace_full_keeps_original_table_when_swap_fails(tmp_path) -> None:
    module = load_script(
        "full_sharadar_refresh_atomic_under_test",
        "scripts/pipeline/full_sharadar_refresh.py",
    )

    db_path = tmp_path / "atomic.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE tickers (ticker VARCHAR, lastupdated DATE, name VARCHAR)")
        conn.execute("INSERT INTO tickers VALUES ('OLD', DATE '2025-01-01', 'Original')")

        replacement = pd.DataFrame(
            {
                "ticker": ["NEW"],
                "lastupdated": [date(2026, 1, 1)],
                "name": ["Replacement"],
            }
        )

        with pytest.raises(RuntimeError, match="injected swap failure"):
            module.replace_full(
                FailingSwapConnection(conn, replacement),
                replacement,
                {"db_table": "tickers"},
            )

        rows = conn.execute(
            "SELECT ticker, lastupdated, name FROM tickers ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [("OLD", date(2025, 1, 1), "Original")]
