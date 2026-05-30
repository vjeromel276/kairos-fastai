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


def full_page_csv(header: str, row_template: str, row_count: int = 10000) -> str:
    rows = [row_template.format(i=i) for i in range(row_count)]
    return header + "\n" + "\n".join(rows) + "\n"


def always_more_pages(csv_text: str):
    def fake_get(url: str, timeout: int) -> FakeResponse:
        if ".json?" in url:
            return FakeResponse(
                json_data={"meta": {"next_cursor_id": "still-more"}},
                content_type="application/json",
            )
        return FakeResponse(text=csv_text)

    return fake_get


def table_names(db_path: Path) -> list[str]:
    conn = duckdb.connect(str(db_path))
    try:
        return conn.execute("SHOW TABLES").fetchdf()["name"].tolist()
    finally:
        conn.close()


def test_sync_page_limit_failure_exits_nonzero_without_creating_table(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "sharadar_data_sync_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )
    monkeypatch.setattr(module, "PAGE_SAFETY_LIMIT", 2)
    monkeypatch.setattr(
        module,
        "check_api_for_new_data",
        lambda *args, **kwargs: (True, date(2026, 1, 2), -1),
    )
    monkeypatch.setenv(module.API_KEY_ENV, "test-key")
    monkeypatch.setattr(
        module.requests,
        "get",
        always_more_pages(
            full_page_csv(
                "date,ticker,close",
                "2026-01-01,T{i},100.0",
            )
        ),
    )

    db_path = tmp_path / "sync.duckdb"
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "sharadar_data_sync.py",
            "--db",
            str(db_path),
            "--tables",
            "SEP",
            "--force",
        ],
    )

    assert module.main() == 1
    assert "sep_base" not in table_names(db_path)


def test_full_refresh_page_limit_failure_exits_nonzero_without_replacing_table(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "full_sharadar_refresh_under_test",
        "scripts/pipeline/full_sharadar_refresh.py",
    )
    monkeypatch.setattr(module, "PAGE_SAFETY_LIMIT", 2)
    monkeypatch.setattr(
        module,
        "check_api_for_new_data",
        lambda *args, **kwargs: (True, date(2026, 1, 2)),
    )
    monkeypatch.setenv(module.API_KEY_ENV, "test-key")
    monkeypatch.setattr(
        module.requests,
        "get",
        always_more_pages(
            full_page_csv(
                (
                    "lastupdated,firstadded,firstpricedate,lastpricedate,"
                    "firstquarter,lastquarter,ticker,name"
                ),
                "2026-01-01,2020-01-01,2020-01-01,2026-01-01,"
                "2025-12-31,2026-03-31,T{i},Name {i}",
            )
        ),
    )

    db_path = tmp_path / "full.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE tickers (ticker VARCHAR, lastupdated DATE, name VARCHAR)")
        conn.execute("INSERT INTO tickers VALUES ('OLD', DATE '2025-01-01', 'Original')")
    finally:
        conn.close()

    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "full_sharadar_refresh.py",
            "--db",
            str(db_path),
            "--tables",
            "TICKERS",
            "--force",
            "--skip-calendar",
        ],
    )

    assert module.main() == 1

    conn = duckdb.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT ticker, lastupdated, name FROM tickers ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("OLD", date(2025, 1, 1), "Original")]
