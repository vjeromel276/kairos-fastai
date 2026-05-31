from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_reload_replaces_same_max_date_changes_without_force(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "full_sharadar_refresh_policy_under_test",
        "scripts/pipeline/full_sharadar_refresh.py",
    )

    db_path = tmp_path / "full-reload-policy.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE tickers (ticker VARCHAR, lastupdated DATE, name VARCHAR)")
        conn.execute("INSERT INTO tickers VALUES ('AAPL', DATE '2026-01-02', 'Old Apple')")
        conn.execute("INSERT INTO tickers VALUES ('MSFT', DATE '2026-01-02', 'Deleted')")

        replacement = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "lastupdated": [date(2026, 1, 2)],
                "name": ["Corrected Apple"],
            }
        )
        monkeypatch.setattr(
            module,
            "check_api_for_new_data",
            lambda *args, **kwargs: (False, date(2026, 1, 2)),
        )
        monkeypatch.setattr(
            module,
            "download_paginated",
            lambda table_name, table_config, since_date, api_key: replacement,
        )

        result = module.refresh_table(
            conn,
            "TICKERS",
            module.TABLES["TICKERS"],
            "test-key",
            check_only=False,
            force=False,
        )

        rows = conn.execute(
            "SELECT ticker, lastupdated, name FROM tickers ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert result["status"] == "updated"
    assert result["rows_before"] == 2
    assert result["rows_after"] == 1
    assert result["rows_added"] == -1
    assert rows == [("AAPL", date(2026, 1, 2), "Corrected Apple")]
