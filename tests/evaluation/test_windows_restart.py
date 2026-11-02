"""Tests for native Windows process execution, restart, and handle release (EVAL-01-S08)."""

from pathlib import Path
import subprocess
import sys
import uuid
import pytest

from job_automation.contracts.enums import ContextStrategy
from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.records import ArmAttempt, ExperimentManifest, PairResult
from job_automation.evaluation.settings import EvaluationSettings


def test_subprocess_evaluation_check_releases_database_handle(tmp_path: Path):
    """Verify CLI process runs to completion and cleanly releases SQLite file locks."""
    eval_dir = (tmp_path / "Subprocess Eval Dir").resolve()
    eval_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "job_automation",
        "evaluation",
        "check",
        "--eval-root",
        str(eval_dir),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "Evaluation check: PASSED" in proc.stdout

    # Verify database file handle is fully released by deleting or moving it
    db_file = eval_dir / "evaluation.db"
    assert db_file.exists()
    # On Windows, attempting to delete an open file raises PermissionError
    db_file.unlink()
    assert not db_file.exists()


def test_subprocess_evaluation_resume_flow(tmp_path: Path):
    """Verify resuming an experiment via native Windows subprocess."""
    eval_dir = (tmp_path / "Subprocess Resume Dir").resolve()
    eval_dir.mkdir(parents=True, exist_ok=True)

    settings = EvaluationSettings(eval_root=str(eval_dir))
    env = create_evaluation_environment(settings)

    exp_id = uuid.uuid4()
    p_id = uuid.uuid4()

    try:
        corpus = EvaluationCorpus.default_synthetic()
        case = corpus.get_case("case_01_eligible_senior_cpp")

        manifest = ExperimentManifest(
            experiment_id=exp_id,
            experiment_name="subprocess_resume_test",
            corpus_version="1.0",
            split_name="development",
            case_ids=[case.case_id],
            profile_snapshot_hash="hash_p",
            search_policy_fingerprint="fp_pol",
            model_identifier="test-model",
            model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )
        env.repository.save_experiment(manifest, status="running")
        env.repository.save_case(case)

        # Incomplete pair: JSON succeeded, RAG failed
        pair = PairResult(
            pair_id=p_id,
            experiment_id=exp_id,
            case_id=case.case_id,
            repetition_index=0,
            execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
            baseline_disposition=case.gold_label.gold_disposition,
            pair_completed=False,
            json_arm=ArmAttempt(
                pair_id=p_id,
                case_id=case.case_id,
                strategy=ContextStrategy.JSON,
                repetition_index=0,
                execution_status="success",
            ),
            rag_arm=ArmAttempt(
                pair_id=p_id,
                case_id=case.case_id,
                strategy=ContextStrategy.RAG,
                repetition_index=0,
                execution_status="failed",
            ),
        )
        env.repository.save_pair_result(pair)
    finally:
        env.close()

    # Now invoke resume command via subprocess
    cmd = [
        sys.executable,
        "-m",
        "job_automation",
        "evaluation",
        "resume",
        "--eval-root",
        str(eval_dir),
        "--experiment-id",
        str(exp_id),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # Exits with 1 due to incomplete pair (LLM assessor not running in subprocess)
    assert proc.returncode == 1
    assert "EVALUATION REPORT:" in proc.stdout
    assert "0 completed, 1 incomplete" in proc.stdout
