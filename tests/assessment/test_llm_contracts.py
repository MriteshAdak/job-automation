"""Tests for MATCH-02 LLM assessment contracts and schema boundaries (M02-01, M02-11)."""

from __future__ import annotations

import uuid
import pytest
from pydantic import ValidationError

from job_automation.assessment.llm_records import (
    AssessmentProposal,
    AssessmentRequest,
    AssessmentRunResult,
    DeterministicDecisionTrace,
    FindingStatus,
    RequirementFindingProposal,
    RequirementItem,
    RequirementObligation,
    RequirementSet,
)
from job_automation.contracts.assessment import (
    Assessment,
    LLMAssessmentMetadata,
    RequirementFinding,
    RuleOutcome,
)
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    HardCriterionResult,
    RequirementCategory,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference, SourceSpan


def test_assessment_proposal_forbids_extra_fields():
    """Model-authored proposal strictly rejects writable model authority fields like final_disposition."""
    finding = RequirementFindingProposal(
        requirement_id="req_0",
        status=FindingStatus.MATCH,
        reason="Demonstrated in Python development",
        score=90.0,
    )

    # Valid proposal
    prop = AssessmentProposal(
        findings=[finding],
        relevance_score=90.0,
        score_scale="0-100",
        summary_reason="Candidate fits well",
    )
    assert prop.relevance_score == 90.0

    # Model attempting to write final_disposition must fail
    with pytest.raises(ValidationError):
        AssessmentProposal(
            findings=[finding],
            relevance_score=90.0,
            score_scale="0-100",
            summary_reason="Candidate fits well",
            final_disposition="eligible",  # Extra field forbidden!
        )


def test_assessment_proposal_rejects_boolean_or_invalid_score():
    """Proposal rejects boolean scores or string scores."""
    finding = RequirementFindingProposal(
        requirement_id="req_0",
        status=FindingStatus.MATCH,
        reason="Demonstrated",
    )

    # Boolean score in finding proposal
    with pytest.raises(ValidationError):
        RequirementFindingProposal(
            requirement_id="req_0",
            status=FindingStatus.MATCH,
            reason="Demonstrated",
            score=True,  # Boolean rejected!
        )

    # Boolean score in overall proposal
    with pytest.raises(ValidationError):
        AssessmentProposal(
            findings=[finding],
            relevance_score=True,  # Boolean rejected!
            score_scale="0-100",
            summary_reason="Summary",
        )

    # Score scale without score
    with pytest.raises(ValidationError):
        AssessmentProposal(
            findings=[finding],
            relevance_score=None,
            score_scale="0-100",  # Cannot provide scale without score
            summary_reason="Summary",
        )

    # Score without score scale
    with pytest.raises(ValidationError):
        AssessmentProposal(
            findings=[finding],
            relevance_score=85.0,
            score_scale=None,  # Required when score is provided
            summary_reason="Summary",
        )

    # Unsupported score scale
    with pytest.raises(ValidationError):
        AssessmentProposal(
            findings=[finding],
            relevance_score=85.0,
            score_scale="1-5",  # Unsupported scale
            summary_reason="Summary",
        )


def test_assessment_run_result_success_pending_exclusivity():
    """AssessmentRunResult enforces strict mutual exclusivity between success and pending states."""
    c11 = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        posting_revision="sha256:" + "a" * 64,
        profile_version="v1",
        policy_version="pol-1.0",
        assessment_method=AssessmentMethod.LLM,
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        relevance_score=88.0,
        score_scale="0-100",
        summary_reason="Eligible fit",
        final_disposition=AssessmentDisposition.ELIGIBLE,
        model_metadata=LLMAssessmentMetadata(
            model_identifier="local-assessor",
            prompt_version="v1",
            context_strategy=ContextStrategy.JSON,
        ),
    )

    # Valid success
    res_success = AssessmentRunResult(
        status="success",
        assessment=c11,
        input_fingerprint="sha256:" + "b" * 64,
        audit_references={"call_id": "test"},
    )
    assert res_success.status == "success"
    assert res_success.assessment is not None

    # Invalid success (carrying error or missing assessment)
    with pytest.raises(ValidationError):
        AssessmentRunResult(
            status="success",
            assessment=None,  # Missing assessment on success
            input_fingerprint="sha256:" + "b" * 64,
        )

    with pytest.raises(ValidationError):
        AssessmentRunResult(
            status="success",
            assessment=c11,
            failed_stage="inference",  # Must not carry failed_stage on success
            input_fingerprint="sha256:" + "b" * 64,
        )

    # Valid pending
    err = ClassifiedError.from_category(ErrorCategory.TRANSIENT_SERVICE, "Service 503")
    res_pending = AssessmentRunResult(
        status="pending",
        assessment=None,
        failed_stage="inference",
        error=err,
        input_fingerprint="sha256:" + "b" * 64,
        deterministic_baseline=c11,
    )
    assert res_pending.status == "pending"
    assert res_pending.error is not None

    # Invalid pending (carrying completed LLM assessment)
    with pytest.raises(ValidationError):
        AssessmentRunResult(
            status="pending",
            assessment=c11,  # Must NOT carry completed assessment on pending!
            failed_stage="inference",
            error=err,
            input_fingerprint="sha256:" + "b" * 64,
        )


def test_legacy_c11_round_trip_compatibility():
    """Rules-only legacy Assessment records round-trip without fictitious LLM metadata."""
    legacy_c11 = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        posting_revision="rev-1",
        profile_version="v1",
        policy_version="pol-1",
        assessment_method=AssessmentMethod.RULES,
        rule_outcomes=[
            RuleOutcome(
                criterion_id="crit_1",
                criterion_name="Work Authorization",
                result=HardCriterionResult.PASS,
                reason="EU Citizen",
            )
        ],
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        summary_reason="Rules passed",
        final_disposition=AssessmentDisposition.ELIGIBLE,
        model_metadata=None,
    )

    data = legacy_c11.model_dump(mode="json")
    rehydrated = Assessment.model_validate(data)

    assert rehydrated.assessment_method == AssessmentMethod.RULES
    assert rehydrated.model_metadata is None
    assert rehydrated.requirement_findings == []
    assert rehydrated.relevance_score is None


def test_extended_c11_with_findings_and_trace_round_trip():
    """C11 records with typed requirement findings and trace reference serialize and round-trip."""
    cand_ref = CandidateEvidenceReference(
        profile_version="v1",
        fact_id=uuid.uuid4(),
    )
    job_ref = JobEvidenceReference(
        posting_revision="sha256:" + "a" * 64,
        field_path="description_clean",
        quotation="5 years Python required",
        source_span=SourceSpan(start=10, end=33),
    )
    finding = RequirementFinding(
        requirement_id="req_0",
        requirement_text="5 years Python required",
        obligation=RequirementObligation.REQUIRED,
        category=RequirementCategory.SKILL,
        status=FindingStatus.MATCH,
        candidate_evidence=[cand_ref],
        job_evidence=job_ref,
        reason="Demonstrated across 2 positions",
        score=95.0,
    )

    c11 = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        posting_revision="sha256:" + "a" * 64,
        profile_version="v1",
        policy_version="pol-1",
        assessment_method=AssessmentMethod.LLM,
        rule_outcomes=[],
        requirement_findings=[finding],
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        relevance_score=92.0,
        score_scale="0-100",
        summary_reason="Strong fit across technical skills",
        final_disposition=AssessmentDisposition.ELIGIBLE,
        model_metadata=LLMAssessmentMetadata(
            model_identifier="local-assessor",
            prompt_version="v1",
            context_strategy=ContextStrategy.JSON,
            model_digest="sha256:model123",
            prompt_fingerprint="sha256:prompt123",
        ),
        validation_issues=[
            ValidationIssue(field_path="findings", code="note", message="Review warning")
        ],
        assessment_input_fingerprint="sha256:input123",
        deterministic_trace_ref="sha256:trace123",
    )

    data = c11.model_dump(mode="json")
    rehydrated = Assessment.model_validate(data)

    assert len(rehydrated.requirement_findings) == 1
    assert rehydrated.requirement_findings[0].requirement_id == "req_0"
    assert rehydrated.requirement_findings[0].candidate_evidence[0].fact_id == cand_ref.fact_id
    assert rehydrated.model_metadata is not None
    assert rehydrated.model_metadata.model_digest == "sha256:model123"
    assert rehydrated.assessment_input_fingerprint == "sha256:input123"
    assert rehydrated.deterministic_trace_ref == "sha256:trace123"
