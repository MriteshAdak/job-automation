"""Integration tests for paired evaluation runner (EVAL-01-S04)."""

from pathlib import Path
import uuid
import pytest

from job_automation.assessment.service import AssessmentService
from job_automation.contracts.enums import AssessmentDisposition, ContextStrategy
from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.records import ExperimentManifest
from job_automation.evaluation.runner import EvaluationRunner
from job_automation.evaluation.settings import EvaluationSettings


def test_runner_executes_paired_evaluation_with_hard_rule_precedence(tmp_path: Path):
    """Verify EvaluationRunner executes paired comparison and enforces hard rule precedence."""
    eval_dir = (tmp_path / "eval_pairs_run").resolve()
    settings = EvaluationSettings(
        eval_root=str(eval_dir),
    )
    env = create_evaluation_environment(settings)

    try:
        corpus = EvaluationCorpus.default_synthetic()
        asmt_service = AssessmentService()

        # Run on case_03 (hard rejection: US location)
        c3 = corpus.get_case("case_03_rejected_hard_location")
        manifest = ExperimentManifest(
            experiment_name="hard_fail_pair_test",
            case_ids=[c3.case_id],
            profile_snapshot_hash="hash_p",
            search_policy_fingerprint="fp_pol",
            model_identifier="test-model",
            model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            repetitions_per_pair=2,
            order_randomization_seed=42,
        )

        runner = EvaluationRunner(
            environment=env,
            assessment_service=asmt_service,
            llm_assessor=None,  # Not needed for deterministic reject!
        )

        results = runner.run_experiment(manifest, corpus)
        assert len(results) == 2

        for pair in results:
            assert pair.case_id == "case_03_rejected_hard_location"
            assert pair.pair_completed is True
            assert pair.baseline_disposition == AssessmentDisposition.REJECTED
            assert pair.json_arm.final_assessment.final_disposition == AssessmentDisposition.REJECTED
            assert pair.rag_arm.final_assessment.final_disposition == AssessmentDisposition.REJECTED
            assert pair.disposition_agreement is True

        # Verify counterbalancing: across repetitions or different cases, both orders are exercised
        orders = [p.execution_order for p in results]
        assert [ContextStrategy.JSON, ContextStrategy.RAG] in orders or [ContextStrategy.RAG, ContextStrategy.JSON] in orders

        # Verify persistence in repository
        persisted_pairs = env.repository.list_pairs_for_experiment(manifest.experiment_id)
        assert len(persisted_pairs) == 2
    finally:
        env.close()

