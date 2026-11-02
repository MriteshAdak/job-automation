"""Tests for metric calculations, zero denominators, and confusion matrices (EVAL-01-S05)."""

import uuid
import pytest

from job_automation.contracts.assessment import (
    Assessment,
    LLMAssessmentMetadata,
    RequirementCategory,
    RequirementFinding,
    RuleOutcome,
)
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    FindingStatus,
    HardCriterionResult,
)
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.evaluation.metrics import (
    calculate_arm_metrics,
    calculate_confusion_matrix,
    calculate_evaluation_metrics,
    calculate_strategy_deltas,
    safe_div,
)
from job_automation.evaluation.records import (
    ArmAttempt,
    EvaluationCase,
    GoldLabelRevision,
    GoldRequirementLabel,
    PairResult,
)


def _make_dummy_assessment(
    disposition: AssessmentDisposition = AssessmentDisposition.ELIGIBLE,
    score: float = 85.0,
    strategy: ContextStrategy = ContextStrategy.JSON,
) -> Assessment:
    return Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        posting_revision="rev_1",
        profile_version="v1",
        policy_version="v1",
        assessment_method=AssessmentMethod.LLM,
        final_disposition=disposition,
        relevance_decision=disposition,
        relevance_score=score,
        score_scale="0-100",
        summary_reason="Match reason",
        model_metadata=LLMAssessmentMetadata(
            model_identifier="test-model",
            prompt_version="v1",
            context_strategy=strategy,
        ),
        rule_outcomes=[],
        requirement_findings=[],
    )


def test_safe_div():
    """Verify zero denominator yields None and never 1.0 or 0.0."""
    assert safe_div(0, 0) is None
    assert safe_div(5, 0) is None
    assert safe_div(0, 5) == 0.0
    assert safe_div(1, 2) == 0.5


def test_zero_denominator_metrics():
    """Verify empty gold facts yield None for coverage rates."""
    pair_id = uuid.uuid4()
    arm = ArmAttempt(
        pair_id=pair_id,
        case_id="case_empty",
        strategy=ContextStrategy.RAG,
        repetition_index=0,
        execution_status="success",
        final_assessment=_make_dummy_assessment(strategy=ContextStrategy.RAG),
        captured_trace={"admitted_fact_ids": [], "raw_retrieved_fact_ids": []},
    )
    # Gold requirements with no evidence sets (pure gaps)
    gold_reqs = [
        GoldRequirementLabel(
            requirement_id="req_empty",
            text="No evidence requirement",
            category=RequirementCategory.SKILL,
            gold_status=FindingStatus.GAP,
            sufficient_evidence_sets=[],
        )
    ]

    metrics = calculate_arm_metrics(arm, gold_reqs)
    assert metrics["retrieval_coverage_raw"] is None
    assert metrics["admitted_evidence_coverage"] is None
    assert metrics["citation_use_rate"] is None


def test_json_retrieval_metrics_are_strictly_none():
    """Verify JSON strategy always reports None for retrieval metrics."""
    fid = "00000000-0000-0000-0000-000000000001"
    pair_id = uuid.uuid4()
    arm = ArmAttempt(
        pair_id=pair_id,
        case_id="case_json",
        strategy=ContextStrategy.JSON,
        repetition_index=0,
        execution_status="success",
        final_assessment=_make_dummy_assessment(strategy=ContextStrategy.JSON),
        captured_trace={"admitted_fact_ids": [fid]},
    )
    gold_reqs = [
        GoldRequirementLabel(
            requirement_id="req_cpp",
            text="C++",
            category=RequirementCategory.SKILL,
            gold_status=FindingStatus.MATCH,
            sufficient_evidence_sets=[[fid]],
        )
    ]

    metrics = calculate_arm_metrics(arm, gold_reqs)
    assert metrics["retrieval_coverage_raw"] is None
    assert metrics["retrieval_coverage_ranked"] is None
    assert metrics["admitted_evidence_coverage"] == 1.0


def test_confusion_matrix_hand_calculated():
    """Verify 3x3 confusion matrix calculation and retention FNR / precision."""
    c1_id = "c1_eligible"
    c2_id = "c2_review"
    c3_id = "c3_rejected"

    def _make_case(cid: str, disp: AssessmentDisposition) -> EvaluationCase:
        from job_automation.evaluation.corpus import EvaluationCorpus
        corp = EvaluationCorpus.default_synthetic()
        base = corp.get_case("case_01_eligible_senior_cpp")
        gl = GoldLabelRevision(
            case_id=cid,
            gold_disposition=disp,
            rationale="Adjudicated test label",
            requirements=[],
        )
        return EvaluationCase(
            case_id=cid,
            canonical_job_id=base.canonical_job_id,
            posting_revision=base.posting_revision,
            profile=base.profile,
            policy=base.policy,
            posting=base.posting,
            gold_label=gl,
            opportunity_group_id=f"grp_{cid}",
        )

    cases = {
        c1_id: _make_case(c1_id, AssessmentDisposition.ELIGIBLE),
        c2_id: _make_case(c2_id, AssessmentDisposition.REVIEW),
        c3_id: _make_case(c3_id, AssessmentDisposition.REJECTED),
    }

    # Case 1: Gold ELIGIBLE -> JSON predicted ELIGIBLE, RAG predicted REVIEW
    # Case 2: Gold REVIEW -> JSON predicted REVIEW, RAG predicted REJECTED (false negative!)
    # Case 3: Gold REJECTED -> JSON predicted REJECTED, RAG predicted REJECTED
    exp_id = uuid.uuid4()
    p1_id = uuid.uuid4()
    p2_id = uuid.uuid4()
    p3_id = uuid.uuid4()

    p1 = PairResult(
        experiment_id=exp_id,
        case_id=c1_id,
        repetition_index=0,
        execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
        baseline_disposition=AssessmentDisposition.ELIGIBLE,
        json_arm=ArmAttempt(
            pair_id=p1_id,
            case_id=c1_id, strategy=ContextStrategy.JSON, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.ELIGIBLE, 90.0, ContextStrategy.JSON),
        ),
        rag_arm=ArmAttempt(
            pair_id=p1_id,
            case_id=c1_id, strategy=ContextStrategy.RAG, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.REVIEW, 70.0, ContextStrategy.RAG),
        ),
    )
    p2 = PairResult(
        experiment_id=exp_id,
        case_id=c2_id,
        repetition_index=0,
        execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
        baseline_disposition=AssessmentDisposition.REVIEW,
        json_arm=ArmAttempt(
            pair_id=p2_id,
            case_id=c2_id, strategy=ContextStrategy.JSON, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.REVIEW, 65.0, ContextStrategy.JSON),
        ),
        rag_arm=ArmAttempt(
            pair_id=p2_id,
            case_id=c2_id, strategy=ContextStrategy.RAG, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.REJECTED, 30.0, ContextStrategy.RAG),
        ),
    )
    p3 = PairResult(
        experiment_id=exp_id,
        case_id=c3_id,
        repetition_index=0,
        execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
        baseline_disposition=AssessmentDisposition.REJECTED,
        json_arm=ArmAttempt(
            pair_id=p3_id,
            case_id=c3_id, strategy=ContextStrategy.JSON, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.REJECTED, 20.0, ContextStrategy.JSON),
        ),
        rag_arm=ArmAttempt(
            pair_id=p3_id,
            case_id=c3_id, strategy=ContextStrategy.RAG, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.REJECTED, 20.0, ContextStrategy.RAG),
        ),
    )

    cm = calculate_confusion_matrix([p1, p2, p3], cases)

    # JSON:
    # Gold Positives = 2 (c1 ELIGIBLE, c2 REVIEW)
    # Predicted: c1 ELIGIBLE, c2 REVIEW -> 0 false negatives
    # FNR = 0.0
    # Precision Eligible = 1 / 1 = 1.0
    assert cm["json"]["gold_positives"] == 2
    assert cm["json"]["false_negatives"] == 0
    assert cm["json"]["fnr_retention"] == 0.0
    assert cm["json"]["precision_eligible"] == 1.0

    # RAG:
    # Gold Positives = 2
    # Predicted: c1 REVIEW, c2 REJECTED -> 1 false negative (c2 was gold REVIEW, predicted REJECTED)
    # FNR = 1 / 2 = 0.5
    # Precision Eligible = 0 predicted eligible -> None (0/0)
    assert cm["rag"]["gold_positives"] == 2
    assert cm["rag"]["false_negatives"] == 1
    assert cm["rag"]["fnr_retention"] == 0.5
    assert cm["rag"]["precision_eligible"] is None


def test_strategy_deltas():
    """Verify paired score delta and disposition agreement calculation."""
    exp_id = uuid.uuid4()
    p1_id = uuid.uuid4()
    p2_id = uuid.uuid4()

    p1 = PairResult(
        experiment_id=exp_id,
        case_id="c1",
        repetition_index=0,
        execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
        baseline_disposition=AssessmentDisposition.ELIGIBLE,
        json_arm=ArmAttempt(
            pair_id=p1_id,
            case_id="c1", strategy=ContextStrategy.JSON, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.ELIGIBLE, 85.0),
        ),
        rag_arm=ArmAttempt(
            pair_id=p1_id,
            case_id="c1", strategy=ContextStrategy.RAG, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.ELIGIBLE, 75.0),
        ),
    )
    p2 = PairResult(
        experiment_id=exp_id,
        case_id="c2",
        repetition_index=0,
        execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
        baseline_disposition=AssessmentDisposition.REVIEW,
        json_arm=ArmAttempt(
            pair_id=p2_id,
            case_id="c2", strategy=ContextStrategy.JSON, repetition_index=0,
            execution_status="success", final_assessment=_make_dummy_assessment(AssessmentDisposition.REVIEW, 60.0),
        ),
        rag_arm=ArmAttempt(
            pair_id=p2_id,
            case_id="c2", strategy=ContextStrategy.RAG, repetition_index=0,
            execution_status="failed",
        ),
    )

    deltas = calculate_strategy_deltas([p1, p2])
    assert deltas["completed_pairs_count"] == 1
    assert deltas["mean_score_delta"] == 10.0
    assert deltas["disposition_agreement_rate"] == 1.0
