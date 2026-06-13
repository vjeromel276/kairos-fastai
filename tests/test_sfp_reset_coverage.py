from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prune_keeps_sfp_source_table(monkeypatch, tmp_path, capsys) -> None:
    module = load_script(
        "prune_to_source_tables_sfp_under_test",
        "scripts/fastai_reset/prune_to_source_tables.py",
    )
    db_path = tmp_path / "prune-sfp.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE sfp (ticker VARCHAR, date DATE)")
        conn.execute("CREATE TABLE derived_feature_table (ticker VARCHAR)")
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prune_to_source_tables.py",
            "--db",
            str(db_path),
            "--dry-run",
        ],
    )

    module.main()
    output = capsys.readouterr().out

    assert "sfp" in output
    assert "Objects to drop: 1" in output
    assert "derived_feature_table" in output


def test_audit_reports_sfp_date_range_and_distinct_tickers(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    module = load_script(
        "audit_source_db_sfp_under_test",
        "scripts/fastai_reset/audit_source_db.py",
    )
    db_path = tmp_path / "audit-sfp.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE sep_base (ticker VARCHAR, date DATE)")
        conn.execute("INSERT INTO sep_base VALUES ('AAPL', DATE '2026-01-02')")
        conn.execute("CREATE TABLE daily (ticker VARCHAR, date DATE)")
        conn.execute("INSERT INTO daily VALUES ('AAPL', DATE '2026-01-02')")
        conn.execute("CREATE TABLE sfp (ticker VARCHAR, date DATE, lastupdated DATE)")
        conn.execute("INSERT INTO sfp VALUES ('FUNDX', DATE '2026-01-02', DATE '2026-01-03')")
        conn.execute("INSERT INTO sfp VALUES ('FUNDY', DATE '2026-01-05', DATE '2026-01-06')")
    finally:
        conn.close()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_source_db.py",
            "--db",
            str(db_path),
        ],
    )

    module.main()
    output = capsys.readouterr().out

    assert "sfp" in output
    assert "2026-01-02" in output
    assert "2026-01-05" in output
    assert "ticker" in output
