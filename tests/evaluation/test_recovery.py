"""Tests for evaluation experiment recovery and resumption (EVAL-01-S03)."""

from pathlib import Path
import uuid
import pytest

from job_automation.contracts.enums import AssessmentDisposition, ContextStrategy
from job_automation.evaluation.records import (
    ArmAttempt,
    ExperimentManifest,
    PairResult,
)
from job_automation.evaluation.recovery import EvaluationRecoveryManager
from job_automation.evaluation.repository import EvaluationRepository


def test_recovery_identifies_completed_and_incomplete_pairs(tmp_path: Path):
    """Verify recovery manager accurately distinguishes completed from pending pairs."""
    db_path = tmp_path / "evaluation.db"
    repo = EvaluationRepository(db_path)

    try:
        exp_id = uuid.uuid4()
        manifest = ExperimentManifest(
            experiment_id=exp_id,
            experiment_name="recovery_test",
            case_ids=["c1", "c2", "c3"],
            profile_snapshot_hash="hash_p",
            search_policy_fingerprint="fp_pol",
            model_identifier="test-model",
            model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            repetitions_per_pair=1,
        )
        repo.save_experiment(manifest)

        # Create dummy assessment
        from job_automation.contracts.assessment import Assessment, RuleOutcome
        from job_automation.contracts.enums import AssessmentMethod, HardCriterionResult
        dummy_asmt = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=uuid.uuid4(),
            posting_revision="rev1",
            profile_version="v1.0",
            policy_version="v1.0",
            assessment_method=AssessmentMethod.RULES,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=85.0,
            score_scale="0-100",
            summary_reason="All hard criteria met",
            rule_outcomes=[
                RuleOutcome(
                    criterion_id="r1",
                    criterion_name="Criterion 1",
                    result=HardCriterionResult.PASS,
                    reason="Passed rule",
                )
            ],
        )

        # Save completed pair for c1
        p1_id = uuid.uuid4()
        pair_c1 = PairResult(
            pair_id=p1_id,
            experiment_id=exp_id,
            case_id="c1",
            execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
            baseline_disposition=AssessmentDisposition.ELIGIBLE,
            json_arm=ArmAttempt(
                pair_id=p1_id,
                case_id="c1",
                strategy=ContextStrategy.JSON,
                execution_status="success",
                final_assessment=dummy_asmt,
            ),
            rag_arm=ArmAttempt(
                pair_id=p1_id,
                case_id="c1",
                strategy=ContextStrategy.RAG,
                execution_status="success",
                final_assessment=dummy_asmt,
            ),
        )
        repo.save_pair_result(pair_c1)

        # Save incomplete pair for c2 (json success, rag failed)
        p2_id = uuid.uuid4()
        pair_c2 = PairResult(
            pair_id=p2_id,
            experiment_id=exp_id,
            case_id="c2",
            execution_order=[ContextStrategy.RAG, ContextStrategy.JSON],
            baseline_disposition=AssessmentDisposition.ELIGIBLE,
            json_arm=ArmAttempt(
                pair_id=p2_id,
                case_id="c2",
                strategy=ContextStrategy.JSON,
                execution_status="success",
                final_assessment=dummy_asmt,
            ),
            rag_arm=ArmAttempt(
                pair_id=p2_id,
                case_id="c2",
                strategy=ContextStrategy.RAG,
                execution_status="failed",
            ),
        )
        repo.save_pair_result(pair_c2)

        # c3 has no record at all

        recovery = EvaluationRecoveryManager(repo)
        plan = recovery.inspect_experiment(exp_id)

        assert plan.total_planned_pairs == 3
        assert plan.completed_pairs_count == 1
        assert ("c1", 0) in plan.completed_pair_keys

        assert plan.incomplete_pairs_count == 2
        assert ("c2", 0) in plan.cases_to_resume
        assert ("c3", 0) in plan.cases_to_resume
    finally:
        repo.close()
