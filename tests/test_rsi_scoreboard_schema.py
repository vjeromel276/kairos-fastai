from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOREBOARD = ROOT / "docs" / "rsi_experiment_scoreboard.md"


def markdown_table_columns(markdown: str) -> list[str]:
    for line in markdown.splitlines():
        if line.startswith("| experiment_id "):
            return [cell.strip() for cell in line.strip("|").split("|")]
    raise AssertionError("scoreboard table header not found")


def test_rsi_scoreboard_has_required_columns() -> None:
    markdown = SCOREBOARD.read_text()
    columns = markdown_table_columns(markdown)

    required_columns = {
        "experiment_id",
        "scope",
        "ticker_set",
        "feature_set",
        "model",
        "target",
        "train_window",
        "validation_window",
        "test_window",
        "validation_metric_summary",
        "test_metric_summary",
        "keep",
        "decision_notes",
        "metrics_path",
        "commit",
    }
    assert required_columns.issubset(columns)


def test_rsi_scoreboard_distinguishes_one_ticker_and_panel_results() -> None:
    markdown = SCOREBOARD.read_text()

    assert "`one_ticker`" in markdown
    assert "`panel`" in markdown
    assert "date-level ranking metrics" in markdown
