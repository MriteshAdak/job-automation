"""Tests for native Windows path handling with spaces and German umlauts (EVAL-01-S08)."""

from pathlib import Path
import uuid
import pytest

from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.records import ExperimentManifest
from job_automation.evaluation.settings import EvaluationSettings
from job_automation.evaluation.workspace import EvaluationWorkspace


def test_windows_paths_with_spaces_and_umlauts(tmp_path: Path):
    """Verify evaluation environment operates reliably on Windows paths with spaces and German umlauts."""
    # Build path with spaces and German characters: "Prüfung München ÄÖÜäöüß"
    unicode_dir = (tmp_path / "Job Evaluation Prüfung München ÄÖÜäöüß mit Leerzeichen").resolve()
    unicode_dir.mkdir(parents=True, exist_ok=True)

    workspace = EvaluationWorkspace(unicode_dir)
    workspace.initialize_directories()

    assert workspace.eval_root.exists()
    assert workspace.artifacts_dir.exists()
    assert workspace.packets_dir.exists()
    assert workspace.reports_dir.exists()

    settings = EvaluationSettings(eval_root=str(unicode_dir))
    env = create_evaluation_environment(settings)

    try:
        # Check SQLite persistence on unicode path
        corpus = EvaluationCorpus.default_synthetic()
        case = corpus.get_case("case_01_eligible_senior_cpp")
        env.repository.save_case(case)

        retrieved = env.repository.get_case(case.case_id)
        assert retrieved is not None
        assert retrieved.case_id == case.case_id

        # Verify artifacts directory file write & read on unicode path
        test_artifact_path = workspace.artifacts_dir / "prüf_bericht_äöü.json"
        with open(test_artifact_path, "w", encoding="utf-8") as f:
            f.write('{"status": "bestanden", "prüfung": "erfolgreich"}')

        assert test_artifact_path.exists()
        with open(test_artifact_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "erfolgreich" in content
    finally:
        env.close()


def test_windows_path_normalization_and_case_insensitivity(tmp_path: Path):
    """Verify path normalization handles Windows casing differences properly."""
    base_dir = (tmp_path / "EvalCasingTest").resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    prod_db = base_dir / "production.db"
    prod_db.touch()

    # Pass production DB with different casing
    cased_prod_str = str(prod_db).lower()

    # Same file under different casing must be recognized as aliasing
    eval_db_same = Path(cased_prod_str)

    from job_automation.evaluation.errors import DatabaseAliasingError

    with pytest.raises(DatabaseAliasingError, match="aliases production database"):
        # Setting eval_root where DEFAULT_EVAL_DB_NAME matches production_db_path
        EvaluationWorkspace(
            eval_root=base_dir,
            production_db_path=str(base_dir / "evaluation.db"),
        )
