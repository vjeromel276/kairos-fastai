from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_result(table_name: str, table_config: dict) -> dict:
    return {
        "table": table_name,
        "db_table": table_config["db_table"],
        "mode": table_config.get("reload_mode", "incremental"),
        "local_max": None,
        "api_max": None,
        "has_new_data": False,
        "rows_before": None,
        "rows_after": None,
        "rows_added": 0,
        "status": "up_to_date",
    }


def test_check_only_default_selects_all_tables_including_opt_ins(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "sharadar_data_sync_check_only_selection_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )
    selected: list[str] = []

    def fake_sync_table(conn, table_name, table_config, api_key, **kwargs):
        selected.append(table_name)
        assert kwargs["check_only"] is True
        return fake_result(table_name, table_config)

    monkeypatch.setenv(module.API_KEY_ENV, "test-key")
    monkeypatch.setattr(module, "sync_table", fake_sync_table)
    monkeypatch.setattr(module, "refresh_trading_calendar", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "sharadar_data_sync.py",
            "--db",
            str(tmp_path / "check-only-selection.duckdb"),
            "--check-only",
        ],
    )

    assert module.main() == 0
    assert selected == list(module.TABLES.keys())
    assert "SFP" in selected
    assert "INDICATORS" in selected


def test_sync_default_selects_non_opt_in_tables(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "sharadar_data_sync_default_selection_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )
    selected: list[str] = []

    def fake_sync_table(conn, table_name, table_config, api_key, **kwargs):
        selected.append(table_name)
        assert kwargs["check_only"] is False
        return fake_result(table_name, table_config)

    monkeypatch.setenv(module.API_KEY_ENV, "test-key")
    monkeypatch.setattr(module, "sync_table", fake_sync_table)
    monkeypatch.setattr(module, "refresh_trading_calendar", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "sharadar_data_sync.py",
            "--db",
            str(tmp_path / "sync-selection.duckdb"),
        ],
    )

    assert module.main() == 0
    assert selected == module.DEFAULT_TABLES
    assert "SFP" not in selected
    assert "INDICATORS" not in selected
