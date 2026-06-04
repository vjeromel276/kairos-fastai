from __future__ import annotations

import importlib.util
import io
import zipfile
from datetime import date
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(
        self,
        json_data: dict | None = None,
        content: bytes = b"",
    ) -> None:
        self._json_data = json_data or {}
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json_data

    def iter_content(self, chunk_size: int = 1024):
        yield self.content


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def zipped_csv(name: str, csv_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_text)
    return buffer.getvalue()


def test_full_reload_bulk_export_ingests_and_deletes_downloads(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "full_sharadar_refresh_bulk_under_test",
        "scripts/pipeline/full_sharadar_refresh.py",
    )
    download_url = "https://download.test/tickers.zip?api_key=raw-secret"
    zip_bytes = zipped_csv(
        "SHARADAR_TICKERS.csv",
        "ticker,lastupdated,name\nAAPL,2026-01-02,Corrected Apple\n",
    )
    requests_seen: list[tuple[str, dict | None]] = []

    def fake_get(
        url: str,
        params: dict | None = None,
        timeout: int = 0,
        stream: bool = False,
    ) -> FakeResponse:
        requests_seen.append((url, params))
        if url.endswith("/TICKERS.json"):
            assert params == {"api_key": "test-key", "qopts.export": "true"}
            return FakeResponse(
                json_data={
                    "datatable_bulk_download": {
                        "file": {
                            "status": "fresh",
                            "link": download_url,
                        },
                        "datatable": {
                            "last_refreshed_time": "2026-01-02 00:00:00 UTC",
                        },
                    }
                }
            )
        assert url == download_url
        assert stream is True
        return FakeResponse(content=zip_bytes)

    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "bulk-refresh.duckdb"
    download_root = tmp_path / "downloads"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE tickers (ticker VARCHAR, lastupdated DATE, name VARCHAR)")
        conn.execute("INSERT INTO tickers VALUES ('OLD', DATE '2025-01-01', 'Original')")

        before, after = module.replace_full_from_bulk_export(
            conn,
            "TICKERS",
            module.TABLES["TICKERS"],
            "test-key",
            download_root,
            keep_downloads=False,
            poll_seconds=0,
            max_attempts=1,
        )

        rows = conn.execute(
            "SELECT ticker, lastupdated, name FROM tickers ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert before == 1
    assert after == 1
    assert rows == [("AAPL", date(2026, 1, 2), "Corrected Apple")]
    assert requests_seen == [
        (
            f"{module.BASE_URL}/TICKERS.json",
            {"api_key": "test-key", "qopts.export": "true"},
        ),
        (download_url, None),
    ]
    assert not any(download_root.iterdir())
