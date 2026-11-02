"""Tests for Windows path handling, spaces, and non-ASCII character support (EVAL-01-S03, S08)."""

from pathlib import Path
import pytest

from job_automation.evaluation.repository import EvaluationRepository
from job_automation.evaluation.settings import EvaluationSettings
from job_automation.evaluation.workspace import EvaluationWorkspace


def test_workspace_and_database_with_spaces_and_umlauts(tmp_path: Path):
    """Verify workspace and SQLite repository function with spaces and German umlauts in paths."""
    unicode_dir = (tmp_path / "Job Evaluation Prüfung ä ö ü").resolve()
    settings = EvaluationSettings(
        eval_root=str(unicode_dir),
    )
    workspace = EvaluationWorkspace.from_settings(settings)
    workspace.initialize_directories()

    assert workspace.eval_root.exists()
    assert workspace.artifacts_dir.exists()
    assert workspace.packets_dir.exists()
    assert workspace.reports_dir.exists()

    repo = EvaluationRepository(workspace.db_path)
    try:
        assert workspace.db_path.exists()
        # Verify tables created
        cursor = repo.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='eval_experiments'")
        assert cursor.fetchone() is not None
    finally:
        repo.close()

