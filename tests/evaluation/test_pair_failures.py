"""Tests for handling arm failures, context overflow, and incomplete pairs (EVAL-01-S04)."""

from pathlib import Path
import uuid
import pytest

from job_automation.assessment.llm_records import AssessmentRunResult
from job_automation.assessment.service import AssessmentService
from job_automation.contracts.enums import AssessmentDisposition, ContextStrategy
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import AssessorV2
from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.records import ExperimentManifest
from job_automation.evaluation.runner import EvaluationRunner
from job_automation.evaluation.settings import EvaluationSettings


class FlakyAssessor(AssessorV2):
    """Fails on RAG strategy with context overflow, succeeds on JSON."""

    def __init__(self, sample_assessment):
        self.sample_assessment = sample_assessment

    def assess(self, request):
        if request.context_strategy == ContextStrategy.RAG:
            return AssessmentRunResult(
                status="pending",
                failed_stage="context_selection",
                error=ClassifiedError.from_category(
                    ErrorCategory.CONTEXT_BUDGET,
                    "RAG context overflowed token budget",
                ),
                input_fingerprint="fp_rag_overflow",
            )
        return AssessmentRunResult(
            status="success",
            assessment=self.sample_assessment,
            input_fingerprint="fp_json_success",
        )


def test_runner_handles_arm_failure_and_marks_pair_incomplete(tmp_path: Path):
    """Verify one-arm failure leaves pair incomplete without crashing runner."""
    eval_dir = (tmp_path / "eval_failures_run").resolve()
    settings = EvaluationSettings(
        eval_root=str(eval_dir),
    )
    env = create_evaluation_environment(settings)

    try:
        corpus = EvaluationCorpus.default_synthetic()
        asmt_service = AssessmentService()

        c1 = corpus.get_case("case_01_eligible_senior_cpp")
        manifest = ExperimentManifest(
            experiment_name="overflow_test",
            case_ids=[c1.case_id],
            profile_snapshot_hash="hash_p",
            search_policy_fingerprint="fp_pol",
            model_identifier="test-model",
            model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            repetitions_per_pair=1,
        )

        from job_automation.contracts.assessment import Assessment, LLMAssessmentMetadata, RuleOutcome
        from job_automation.contracts.enums import AssessmentMethod, HardCriterionResult
        dummy_asmt = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=c1.canonical_job_id,
            posting_revision=c1.posting_revision,
            profile_version=c1.profile.profile_version,
            policy_version=c1.policy.policy_version,
            assessment_method=AssessmentMethod.LLM,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=88.0,
            score_scale="0-100",
            summary_reason="Eligible fit",
            model_metadata=LLMAssessmentMetadata(
                model_identifier="test-model",
                prompt_version="v1",
                context_strategy=ContextStrategy.JSON,
            ),
            rule_outcomes=[
                RuleOutcome(
                    criterion_id="crit_location",
                    criterion_name="Germany location",
                    result=HardCriterionResult.PASS,
                    reason="In Germany",
                )
            ],
        )

        flaky_assessor = FlakyAssessor(dummy_asmt)
        runner = EvaluationRunner(
            environment=env,
            assessment_service=asmt_service,
            llm_assessor=flaky_assessor,
        )

        results = runner.run_experiment(manifest, corpus)
        assert len(results) == 1
        pair = results[0]

        assert pair.pair_completed is False
        assert pair.json_arm.execution_status == "success"
        assert pair.rag_arm.execution_status == "overflow"
        assert pair.strategy_delta_score is None
        assert pair.disposition_agreement is None
    finally:
        env.close()
