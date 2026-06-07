from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(
        self,
        text: str = "",
        json_data: dict | None = None,
        content_type: str = "text/csv",
    ) -> None:
        self.text = text
        self._json_data = json_data or {}
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json_data


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def calendar_dates(db_path: Path) -> list[date]:
    conn = duckdb.connect(str(db_path))
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT trading_date FROM trading_calendar ORDER BY trading_date"
            ).fetchall()
        ]
    finally:
        conn.close()


def test_daily_sync_refreshes_trading_calendar_after_sep_update(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "sharadar_data_sync_calendar_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )

    def fake_get(url: str, params: dict | None = None, timeout: int = 0) -> FakeResponse:
        if url.endswith(".json"):
            return FakeResponse(
                json_data={"datatable": {"data": [["2026-01-03"]]}},
                content_type="application/json",
            )
        return FakeResponse(
            text=(
                "date,ticker,close\n"
                "2026-01-03,AAPL,101.0\n"
            )
        )

    monkeypatch.setenv(module.API_KEY_ENV, "test-key")
    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "sync-calendar.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE sep_base (date DATE, ticker VARCHAR, close DOUBLE)")
        conn.execute("INSERT INTO sep_base VALUES (DATE '2026-01-02', 'AAPL', 100.0)")
        conn.execute("CREATE TABLE trading_calendar (trading_date DATE)")
        conn.execute("INSERT INTO trading_calendar VALUES (DATE '2026-01-02')")
    finally:
        conn.close()

    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "sharadar_data_sync.py",
            "--db",
            str(db_path),
            "--tables",
            "SEP",
        ],
    )

    assert module.main() == 0
    assert calendar_dates(db_path) == [date(2026, 1, 2), date(2026, 1, 3)]


def test_daily_sync_check_only_does_not_mutate_stale_trading_calendar(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "sharadar_data_sync_calendar_check_only_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )

    def fake_get(url: str, params: dict | None = None, timeout: int = 0) -> FakeResponse:
        return FakeResponse(
            json_data={"datatable": {"data": [["2026-01-03"]]}},
            content_type="application/json",
        )

    monkeypatch.setenv(module.API_KEY_ENV, "test-key")
    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "sync-calendar-check-only.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE sep_base (date DATE, ticker VARCHAR, close DOUBLE)")
        conn.execute("INSERT INTO sep_base VALUES (DATE '2026-01-02', 'AAPL', 100.0)")
        conn.execute("INSERT INTO sep_base VALUES (DATE '2026-01-03', 'AAPL', 101.0)")
        conn.execute("CREATE TABLE trading_calendar (trading_date DATE)")
        conn.execute("INSERT INTO trading_calendar VALUES (DATE '2026-01-02')")
    finally:
        conn.close()

    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "sharadar_data_sync.py",
            "--db",
            str(db_path),
            "--tables",
            "SEP",
            "--check-only",
        ],
    )

    assert module.main() == 0
    assert calendar_dates(db_path) == [date(2026, 1, 2)]
