"""Tests for reviewer packet generation and blinding (EVAL-01-S06)."""

import json
from pathlib import Path
import uuid
import pytest

from job_automation.contracts.assessment import Assessment, LLMAssessmentMetadata
from job_automation.contracts.enums import AssessmentDisposition, AssessmentMethod, ContextStrategy
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.records import ArmAttempt, PairResult
from job_automation.evaluation.review import generate_blinded_review_packet
from job_automation.evaluation.review_export import export_review_packets


def _make_dummy_assessment(disposition: AssessmentDisposition, strategy: ContextStrategy) -> Assessment:
    return Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        posting_revision="rev_1",
        profile_version="v1",
        policy_version="v1",
        assessment_method=AssessmentMethod.LLM,
        final_disposition=disposition,
        relevance_decision=disposition,
        relevance_score=85.0,
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


def test_blinded_review_packet_generation():
    """Verify that arm strategy identities are blinded in review packet."""
    corpus = EvaluationCorpus.default_synthetic()
    case = corpus.get_case("case_01_eligible_senior_cpp")

    exp_id = uuid.uuid4()
    p_id = uuid.uuid4()
    pair = PairResult(
        experiment_id=exp_id,
        case_id=case.case_id,
        repetition_index=0,
        execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
        baseline_disposition=AssessmentDisposition.ELIGIBLE,
        json_arm=ArmAttempt(
            pair_id=p_id,
            case_id=case.case_id,
            strategy=ContextStrategy.JSON,
            repetition_index=0,
            execution_status="success",
            final_assessment=_make_dummy_assessment(AssessmentDisposition.ELIGIBLE, ContextStrategy.JSON),
        ),
        rag_arm=ArmAttempt(
            pair_id=p_id,
            case_id=case.case_id,
            strategy=ContextStrategy.RAG,
            repetition_index=0,
            execution_status="success",
            final_assessment=_make_dummy_assessment(AssessmentDisposition.REVIEW, ContextStrategy.RAG),
        ),
    )

    pkt = generate_blinded_review_packet(case, pair, seed=42)
    assert pkt.arm_a.arm_label == "Arm A"
    assert pkt.arm_b.arm_label == "Arm B"
    assert pkt.blinding_key in ("A=JSON;B=RAG", "A=RAG;B=JSON")
    assert pkt.case_id == case.case_id
    assert pkt.posting_title == case.posting.title


def test_export_review_packets(tmp_path: Path):
    """Verify export of review packets to a clean JSON file."""
    corpus = EvaluationCorpus.default_synthetic()
    case = corpus.get_case("case_01_eligible_senior_cpp")

    exp_id = uuid.uuid4()
    p_id = uuid.uuid4()
    pair = PairResult(
        experiment_id=exp_id,
        case_id=case.case_id,
        repetition_index=0,
        execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
        baseline_disposition=AssessmentDisposition.ELIGIBLE,
        json_arm=ArmAttempt(
            pair_id=p_id,
            case_id=case.case_id,
            strategy=ContextStrategy.JSON,
            repetition_index=0,
            execution_status="success",
            final_assessment=_make_dummy_assessment(AssessmentDisposition.ELIGIBLE, ContextStrategy.JSON),
        ),
        rag_arm=ArmAttempt(
            pair_id=p_id,
            case_id=case.case_id,
            strategy=ContextStrategy.RAG,
            repetition_index=0,
            execution_status="success",
            final_assessment=_make_dummy_assessment(AssessmentDisposition.REVIEW, ContextStrategy.RAG),
        ),
    )

    out_file = tmp_path / "review_packets.json"
    exported_path = export_review_packets([case], [pair], out_file)
    assert exported_path.exists()

    with open(exported_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["total_packets"] == 1
    assert len(data["packets"]) == 1
    assert "correction_template_example" in data

