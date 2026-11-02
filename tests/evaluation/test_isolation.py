"""Tests for evaluation persistence isolation and database separation (EVAL-01-S03)."""

from pathlib import Path
import uuid
import pytest

from job_automation.contracts.enums import AssessmentDisposition, ContextStrategy
from job_automation.evaluation.corpus import build_canonical_synthetic_cases
from job_automation.evaluation.errors import DatabaseAliasingError
from job_automation.evaluation.records import (
    ArmAttempt,
    ExperimentManifest,
    PairResult,
    ReviewCorrection,
)
from job_automation.evaluation.repository import EvaluationRepository
from job_automation.evaluation.workspace import EvaluationWorkspace
from job_automation.storage.engine import StorageEngine


def test_eval_db_does_not_contain_production_tables(tmp_path: Path):
    """Verify evaluation database only creates eval_* tables and no production tables."""
    db_path = tmp_path / "evaluation.db"
    repo = EvaluationRepository(db_path)
    try:
        cursor = repo.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        # Verify eval tables exist
        assert "eval_experiments" in tables
        assert "eval_cases" in tables
        assert "eval_pairs" in tables
        assert "eval_arm_attempts" in tables
        assert "eval_corrections" in tables
        assert "eval_reports" in tables

        # Verify production tables do NOT exist
        assert "assessments" not in tables
        assert "sync_outbox" not in tables
        assert "runs" not in tables
        assert "posting_bindings" not in tables
        assert "assessment_selections" not in tables
    finally:
        repo.close()


def test_database_aliasing_detection(tmp_path: Path):
    """Verify DatabaseAliasingError is raised when evaluation DB matches production DB."""
    shared_db = (tmp_path / "shared.db").resolve()
    eval_root = (tmp_path / "eval_dir").resolve()

    # Even with case variations or path resolution, aliasing must be detected
    with pytest.raises(DatabaseAliasingError, match="Evaluation database path .* aliases production database"):
        # If eval_root / "evaluation.db" equals production_db_path:
        EvaluationWorkspace(
            eval_root=eval_root,
            production_db_path=eval_root / "evaluation.db",
        )


def test_evaluation_writes_do_not_affect_production_database(tmp_path: Path):
    """Verify operations in evaluation repository leave production database tables untouched."""
    prod_db = tmp_path / "prod.db"
    prod_engine = StorageEngine(
        db_path=prod_db,
        raw_dir=tmp_path / "raw",
        artifacts_dir=tmp_path / "artifacts",
    )
    prod_engine.initialize_schema()

    eval_db = tmp_path / "eval.db"
    eval_repo = EvaluationRepository(eval_db)

    try:
        # Save experiment and case in eval repo
        cases = build_canonical_synthetic_cases()
        eval_repo.save_case(cases[0])

        manifest = ExperimentManifest(
            experiment_name="test_exp",
            case_ids=[cases[0].case_id],
            profile_snapshot_hash="hash_p",
            search_policy_fingerprint="fp_pol",
            model_identifier="test-model",
            model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )
        eval_repo.save_experiment(manifest)

        # Assert production assessments table is still empty
        cursor = prod_engine.conn.execute("SELECT COUNT(*) FROM assessments")
        assert cursor.fetchone()[0] == 0

        # Assert production runs table is still empty
        cursor = prod_engine.conn.execute("SELECT COUNT(*) FROM runs")
        assert cursor.fetchone()[0] == 0
    finally:
        eval_repo.close()
        prod_engine.close()

