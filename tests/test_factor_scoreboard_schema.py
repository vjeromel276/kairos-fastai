from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOREBOARD = ROOT / "docs" / "factor_experiment_scoreboard.md"


def markdown_table_columns(markdown: str) -> list[str]:
    for line in markdown.splitlines():
        if line.startswith("| experiment_id "):
            return [cell.strip() for cell in line.strip("|").split("|")]
    raise AssertionError("factor scoreboard table header not found")


def test_factor_scoreboard_has_required_columns() -> None:
    markdown = SCOREBOARD.read_text()
    columns = markdown_table_columns(markdown)

    required_columns = {
        "experiment_id",
        "run_type",
        "panel_name",
        "ticker_set",
        "bucket_stack",
        "feature_count",
        "model",
        "target",
        "train_window",
        "validation_window",
        "test_window",
        "embargo",
        "validation_metric_summary",
        "test_metric_summary",
        "turnover_summary",
        "cost_adjusted_summary",
        "liquidity_summary",
        "keep",
        "decision_notes",
        "metrics_path",
        "artifact_path",
        "commit",
    }
    assert required_columns.issubset(columns)


def test_factor_scoreboard_distinguishes_run_types_and_panels() -> None:
    markdown = SCOREBOARD.read_text()

    assert "`bucket_only`" in markdown
    assert "`cumulative`" in markdown
    assert "`final_combined`" in markdown
    assert "`large_cap_fixed`" in markdown
    assert "`universe_fastai_v1`" in markdown
    assert "turnover" in markdown
    assert "transaction-cost" in markdown
