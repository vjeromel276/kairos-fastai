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
        text: str = "",
        json_data: dict | None = None,
        content: bytes = b"",
        content_type: str = "text/csv",
    ) -> None:
        self.text = text
        self._json_data = json_data or {}
        self.content = content
        self.headers = {"content-type": content_type}

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


def test_daily_sync_bootstraps_missing_sfp_with_bulk_export(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "sharadar_data_sync_bulk_bootstrap_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )
    download_url = "https://download.test/sfp.zip?api_key=raw-secret"
    zip_bytes = zipped_csv(
        "SHARADAR_SFP.csv",
        "ticker,date,lastupdated,close\nFUNDX,2026-01-02,2026-01-03,10.5\n",
    )
    requests_seen: list[tuple[str, dict | None, bool]] = []

    monkeypatch.setattr(
        module,
        "check_api_for_new_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("bulk bootstrap should not use incremental API check")
        ),
    )

    def fake_get(
        url: str,
        params: dict | None = None,
        timeout: int = 0,
        stream: bool = False,
    ) -> FakeResponse:
        requests_seen.append((url, params, stream))
        if url.endswith("/SFP.json"):
            assert params == {"api_key": "test-key", "qopts.export": "true"}
            return FakeResponse(
                json_data={
                    "datatable_bulk_download": {
                        "file": {"status": "fresh", "link": download_url}
                    }
                },
                content_type="application/json",
            )
        assert url == download_url
        assert stream is True
        return FakeResponse(content=zip_bytes)

    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "daily-bootstrap.duckdb"
    download_root = tmp_path / "downloads"
    conn = duckdb.connect(str(db_path))
    try:
        result = module.sync_table(
            conn,
            "SFP",
            module.TABLES["SFP"],
            "test-key",
            check_only=False,
            force=False,
            download_root=download_root,
            bulk_poll_seconds=0,
            bulk_max_attempts=1,
        )
        rows = conn.execute(
            "SELECT ticker, date, lastupdated, close FROM sfp ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert result["status"] == "updated"
    assert result["rows_before"] == 0
    assert result["rows_after"] == 1
    assert result["local_max"] == date(2026, 1, 2)
    assert rows == [("FUNDX", date(2026, 1, 2), date(2026, 1, 3), 10.5)]
    assert requests_seen == [
        (f"{module.BASE_URL}/SFP.json", {"api_key": "test-key", "qopts.export": "true"}, False),
        (download_url, None, True),
    ]
    assert not any(download_root.iterdir())


def test_daily_sync_uses_incremental_pagination_after_sf3_exists(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "sharadar_data_sync_post_bootstrap_under_test",
        "scripts/pipeline/sharadar_data_sync.py",
    )
    requests_seen: list[tuple[str, dict | None]] = []

    monkeypatch.setattr(
        module,
        "replace_full_from_bulk_export",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("existing SF3 should use incremental pagination")
        ),
    )

    def fake_get(url: str, params: dict | None = None, timeout: int = 0) -> FakeResponse:
        requests_seen.append((url, params))
        assert params is not None
        assert params.get("qopts.export") is None
        if url.endswith(".json"):
            assert params.get("calendardate.gte") == "2026-01-02"
            return FakeResponse(
                json_data={"datatable": {"data": [["2026-01-02"]]}},
                content_type="application/json",
            )
        assert url.endswith("/SF3.csv")
        assert params.get("calendardate.gte") == "2026-01-02"
        return FakeResponse(
            text="ticker,calendardate,shares\nAAPL,2026-01-02,200\n",
        )

    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "daily-post-bootstrap.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE sf3 (ticker VARCHAR, calendardate DATE, shares BIGINT)")
        conn.execute("INSERT INTO sf3 VALUES ('AAPL', DATE '2026-01-01', 100)")

        result = module.sync_table(
            conn,
            "SF3",
            module.TABLES["SF3"],
            "test-key",
            check_only=False,
            force=False,
        )
        rows = conn.execute(
            "SELECT ticker, calendardate, shares FROM sf3 ORDER BY calendardate"
        ).fetchall()
    finally:
        conn.close()

    assert result["status"] == "updated"
    assert result["local_max"] == date(2026, 1, 2)
    assert rows == [
        ("AAPL", date(2026, 1, 1), 100),
        ("AAPL", date(2026, 1, 2), 200),
    ]
    assert [url for url, _ in requests_seen] == [
        f"{module.BASE_URL}/SF3.json",
        f"{module.BASE_URL}/SF3.csv",
    ]


def test_full_refresh_bootstraps_missing_sf3_with_bulk_export(
    monkeypatch,
    tmp_path,
) -> None:
    module = load_script(
        "full_sharadar_refresh_bulk_bootstrap_under_test",
        "scripts/pipeline/full_sharadar_refresh.py",
    )
    download_url = "https://download.test/sf3.zip?api_key=raw-secret"
    zip_bytes = zipped_csv(
        "SHARADAR_SF3.csv",
        "ticker,calendardate,shares\nAAPL,2026-01-02,200\n",
    )

    monkeypatch.setattr(
        module,
        "check_api_for_new_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("bulk bootstrap should not use incremental API check")
        ),
    )

    def fake_get(
        url: str,
        params: dict | None = None,
        timeout: int = 0,
        stream: bool = False,
    ) -> FakeResponse:
        if url.endswith("/SF3.json"):
            assert params == {"api_key": "test-key", "qopts.export": "true"}
            return FakeResponse(
                json_data={
                    "datatable_bulk_download": {
                        "file": {"status": "fresh", "link": download_url}
                    }
                },
                content_type="application/json",
            )
        assert url == download_url
        assert stream is True
        return FakeResponse(content=zip_bytes)

    monkeypatch.setattr(module.requests, "get", fake_get)

    db_path = tmp_path / "full-bootstrap.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        result = module.refresh_table(
            conn,
            "SF3",
            module.TABLES["SF3"],
            "test-key",
            check_only=False,
            force=False,
            download_root=tmp_path / "downloads",
            bulk_poll_seconds=0,
            bulk_max_attempts=1,
        )
        rows = conn.execute(
            "SELECT ticker, calendardate, shares FROM sf3 ORDER BY ticker"
        ).fetchall()
    finally:
        conn.close()

    assert result["status"] == "updated"
    assert result["rows_before"] == 0
    assert result["rows_after"] == 1
    assert result["local_max"] == date(2026, 1, 2)
    assert rows == [("AAPL", date(2026, 1, 2), 200)]
