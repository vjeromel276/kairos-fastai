from __future__ import annotations

import importlib.util
from datetime import date
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


def fake_result(
    table_name: str,
    table_config: dict,
    status: str,
    local_max: date | None,
    api_max: date | None = None,
    rows_added: int = 0,
) -> dict:
    return {
        "table": table_name,
        "db_table": table_config["db_table"],
        "mode": table_config.get("reload_mode", "incremental"),
        "local_max": local_max,
        "api_max": api_max,
        "has_new_data": status == "updated",
        "rows_before": None,
        "rows_after": None,
        "rows_added": rows_added,
        "status": status,
    }


def test_model_required_tables_follow_standard_non_opt_in_sources() -> None:
    module = load_script(
        "pre_model_freshness_required_tables_under_test",
        "scripts/pipeline/pre_model_freshness_gate.py",
    )

    assert module.MODEL_REQUIRED_TABLES == module.sync.DEFAULT_TABLES
    assert "SF3" in module.MODEL_REQUIRED_TABLES
    assert "TICKERS" in module.MODEL_REQUIRED_TABLES
    assert "SFP" not in module.MODEL_REQUIRED_TABLES
    assert "INDICATORS" not in module.MODEL_REQUIRED_TABLES


def test_pre_model_gate_updates_sources_and_refreshes_calendar(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "pre_model_freshness_update_under_test",
        "scripts/pipeline/pre_model_freshness_gate.py",
    )
    calls: list[tuple[str, bool]] = []

    def fake_sync_table(conn, table_name, table_config, api_key, **kwargs):
        calls.append((table_name, kwargs["check_only"]))
        assert api_key == "test-key"
        if table_name == "SEP":
            conn.execute(
                "INSERT INTO sep_base VALUES (DATE '2026-01-03', 'AAPL', 101.0)"
            )
            return fake_result(
                table_name,
                table_config,
                "updated",
                date(2026, 1, 3),
                api_max=date(2026, 1, 3),
                rows_added=1,
            )
        if table_name == "DAILY":
            return fake_result(
                table_name,
                table_config,
                "up_to_date",
                date(2026, 1, 2),
                api_max=date(2026, 1, 2),
            )
        if table_name == "TICKERS":
            conn.execute("DELETE FROM tickers")
            conn.execute(
                "INSERT INTO tickers VALUES ('AAPL', DATE '2026-01-03', 'Apple')"
            )
            return fake_result(
                table_name,
                table_config,
                "updated",
                date(2026, 1, 3),
            )
        raise AssertionError(f"unexpected table {table_name}")

    monkeypatch.setattr(module.sync, "sync_table", fake_sync_table)

    db_path = tmp_path / "pre-model-update.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE sep_base (date DATE, ticker VARCHAR, close DOUBLE)")
        conn.execute("INSERT INTO sep_base VALUES (DATE '2026-01-02', 'AAPL', 100.0)")
        conn.execute("CREATE TABLE daily (date DATE, ticker VARCHAR)")
        conn.execute("INSERT INTO daily VALUES (DATE '2026-01-02', 'AAPL')")
        conn.execute("CREATE TABLE tickers (ticker VARCHAR, lastupdated DATE, name VARCHAR)")
        conn.execute("INSERT INTO tickers VALUES ('AAPL', DATE '2026-01-01', 'Old Apple')")
        conn.execute("CREATE TABLE trading_calendar (trading_date DATE)")
        conn.execute("INSERT INTO trading_calendar VALUES (DATE '2026-01-02')")

        gate_result = module.run_gate(
            conn=conn,
            api_key="test-key",
            selected_tables=["SEP", "DAILY", "TICKERS"],
            check_only=False,
            max_staleness_days=0,
            reference_policy="refresh",
        )
        calendar_dates = [
            row[0]
            for row in conn.execute(
                "SELECT trading_date FROM trading_calendar ORDER BY trading_date"
            ).fetchall()
        ]
        ticker_rows = conn.execute(
            "SELECT ticker, lastupdated, name FROM tickers ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert gate_result["passed"] is True
    assert gate_result["blockers"] == []
    assert calls == [("SEP", False), ("DAILY", False), ("TICKERS", False)]
    assert gate_result["calendar_result"]["status"] == "updated"
    assert calendar_dates == [date(2026, 1, 2), date(2026, 1, 3)]
    assert ticker_rows == [("AAPL", date(2026, 1, 3), "Apple")]


def test_pre_model_gate_reports_reference_refresh_when_policy_is_report(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "pre_model_freshness_reference_report_under_test",
        "scripts/pipeline/pre_model_freshness_gate.py",
    )

    monkeypatch.setattr(
        module.sync,
        "sync_table",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("report policy should not refresh full-reference tables")
        ),
    )

    db_path = tmp_path / "pre-model-reference-report.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE tickers (ticker VARCHAR, lastupdated DATE)")
        conn.execute("INSERT INTO tickers VALUES ('AAPL', DATE '2026-01-02')")

        gate_result = module.run_gate(
            conn=conn,
            api_key="test-key",
            selected_tables=["TICKERS"],
            check_only=False,
            max_staleness_days=0,
            reference_policy="report",
        )
    finally:
        conn.close()

    assert gate_result["passed"] is False
    assert gate_result["results"][0]["status"] == "needs_reference_refresh"
    assert gate_result["blockers"] == [
        "TICKERS requires reference refresh before model use"
    ]


def test_pre_model_gate_fails_when_required_source_remains_stale(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "pre_model_freshness_stale_under_test",
        "scripts/pipeline/pre_model_freshness_gate.py",
    )

    def fake_sync_table(conn, table_name, table_config, api_key, **kwargs):
        assert table_name == "DAILY"
        return fake_result(
            table_name,
            table_config,
            "updated",
            date(2026, 1, 1),
            api_max=date(2026, 1, 5),
        )

    monkeypatch.setattr(module.sync, "sync_table", fake_sync_table)

    db_path = tmp_path / "pre-model-stale.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE daily (date DATE, ticker VARCHAR)")
        conn.execute("INSERT INTO daily VALUES (DATE '2026-01-01', 'AAPL')")

        gate_result = module.run_gate(
            conn=conn,
            api_key="test-key",
            selected_tables=["DAILY"],
            check_only=False,
            max_staleness_days=1,
            reference_policy="refresh",
        )
    finally:
        conn.close()

    assert gate_result["passed"] is False
    assert gate_result["blockers"] == [
        "DAILY is 4 day(s) behind API max 2026-01-05; allowed lag is 1"
    ]
