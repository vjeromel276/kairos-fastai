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


def test_daily_sync_refreshes_same_date_gte_correction(monkeypatch, tmp_path) -> None:
    module = load_script(
        "sharadar_data_sync_overlap_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )
    requested_urls: list[str] = []

    def fake_get(url: str, timeout: int) -> FakeResponse:
        requested_urls.append(url)
        if ".json?" in url:
            return FakeResponse(
                json_data={"datatable": {"data": [["2026-01-02"]]}},
                content_type="application/json",
            )
        return FakeResponse(
            text=(
                "ticker,dimension,datekey,reportperiod,lastupdated,revenue\n"
                "AAPL,ARQ,2025-12-31,2025-12-31,2026-01-02,200\n"
            )
        )

    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "sync-overlap.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE sf1 (
                ticker VARCHAR,
                dimension VARCHAR,
                datekey DATE,
                reportperiod DATE,
                lastupdated DATE,
                revenue BIGINT
            )
        """)
        conn.execute("""
            INSERT INTO sf1
            VALUES ('AAPL', 'ARQ', DATE '2025-12-31', DATE '2025-12-31',
                    DATE '2026-01-02', 100)
        """)

        result = module.sync_table(
            conn,
            "SF1",
            module.TABLES["SF1"],
            "test-key",
            check_only=False,
            force=False,
        )

        rows = conn.execute(
            "SELECT ticker, lastupdated, revenue FROM sf1 ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert result["status"] == "updated"
    assert rows == [("AAPL", date(2026, 1, 2), 200)]
    assert any("lastupdated.gte=2026-01-02" in url for url in requested_urls)
    assert not any("lastupdated.gte=2026-01-03" in url for url in requested_urls)


def test_full_refresh_refreshes_same_date_gte_correction(monkeypatch, tmp_path) -> None:
    module = load_script(
        "full_sharadar_refresh_overlap_under_test",
        "scripts/pipeline/full_sharadar_refresh.py",
    )
    requested_urls: list[str] = []

    def fake_get(url: str, timeout: int) -> FakeResponse:
        requested_urls.append(url)
        if ".json?" in url:
            return FakeResponse(
                json_data={"datatable": {"data": [["2026-01-02"]]}},
                content_type="application/json",
            )
        return FakeResponse(
            text=(
                "ticker,date,lastupdated,marketcap\n"
                "AAPL,2026-01-01,2026-01-02,200\n"
            )
        )

    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "full-overlap.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE sharadar_metrics (
                ticker VARCHAR,
                date DATE,
                lastupdated DATE,
                marketcap BIGINT
            )
        """)
        conn.execute("""
            INSERT INTO sharadar_metrics
            VALUES ('AAPL', DATE '2026-01-01', DATE '2026-01-02', 100)
        """)

        result = module.refresh_table(
            conn,
            "METRICS",
            module.TABLES["METRICS"],
            "test-key",
            check_only=False,
            force=False,
        )

        rows = conn.execute(
            "SELECT ticker, lastupdated, marketcap FROM sharadar_metrics ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert result["status"] == "updated"
    assert rows == [("AAPL", date(2026, 1, 2), 200)]
    assert any("lastupdated.gte=2026-01-02" in url for url in requested_urls)
    assert not any("lastupdated.gte=2026-01-03" in url for url in requested_urls)
