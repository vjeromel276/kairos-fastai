from __future__ import annotations

import importlib.util
import logging
from datetime import date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("module_name", "relative_path"),
    [
        ("sync_redaction_under_test", "scripts/pipeline/sharadar_data_sync.py"),
        ("full_redaction_under_test", "scripts/pipeline/full_sharadar_refresh.py"),
    ],
)
def test_redact_api_key_handles_urls_and_params_repr(module_name, relative_path) -> None:
    module = load_script(module_name, relative_path)
    secret = "raw-secret"

    redacted = module.redact_api_key(
        "GET https://example.test/table.csv?api_key=raw-secret&x=1 "
        "{'api_key': 'raw-secret'}"
    )

    assert secret not in redacted
    assert redacted.count("<redacted>") == 2


@pytest.mark.parametrize(
    ("module_name", "relative_path", "table_name", "expected_result"),
    [
        (
            "sync_failure_redaction_under_test",
            "scripts/pipeline/sharadar_data_sync.py",
            "SF1",
            (False, None, 0),
        ),
        (
            "full_failure_redaction_under_test",
            "scripts/pipeline/full_sharadar_refresh.py",
            "SF1",
            (False, None),
        ),
    ],
)
def test_check_api_failure_logs_redacted_api_key(
    caplog,
    monkeypatch,
    module_name,
    relative_path,
    table_name,
    expected_result,
) -> None:
    module = load_script(module_name, relative_path)
    secret = "raw-secret"

    def fake_get(url: str, params: dict | None = None, timeout: int = 0):
        assert "api_key" not in url
        assert params is not None
        assert params["api_key"] == secret
        raise RuntimeError(f"boom {url}?api_key={secret}&x=1 {params}")

    monkeypatch.setattr(module.requests, "get", fake_get)

    with caplog.at_level(logging.WARNING):
        result = module.check_api_for_new_data(
            table_name,
            module.TABLES[table_name],
            date(2026, 1, 2),
            secret,
        )

    assert result == expected_result
    assert secret not in caplog.text
    assert "<redacted>" in caplog.text
