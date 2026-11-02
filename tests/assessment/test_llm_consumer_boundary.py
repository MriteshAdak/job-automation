"""Tests for consumer boundaries, run result serialization, and legacy adapter (M02-12, M02-13)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_automation.assessment.llm_records import (
    AssessmentLimits,
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
from job_automation.assessment.llm_result import deserialize_run_result, serialize_run_result
from job_automation.assessment.llm_service import LegacyAssessorAdapter, LLMAssessmentService
from job_automation.contracts.assessment import (
    Assessment,
    LLMAssessmentMetadata,
    RequirementFinding,
    RuleOutcome,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    HardCriterionResult,
    WorkplaceType,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference, SourceSpan
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.models import ModelResult, TokenUsage
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import create_selector_test_snapshot


def make_test_assessment() -> Assessment:
    job_id = uuid.uuid4()
    posting_rev = "sha256:" + "c" * 64
    snapshot = create_selector_test_snapshot()
    fact1 = snapshot.evidence_records[0]

    finding = RequirementFinding(
        requirement_id="req-1",
        requirement_text="Python experience required",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        status=FindingStatus.MATCH,
        reason="Demonstrated Python skills",
        score=95.0,
        candidate_evidence=[
            CandidateEvidenceReference(profile_version=snapshot.profile_version, fact_id=fact1.fact_id)
        ],
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="description_clean",
            quotation="Python experience required",
            source_span=SourceSpan(start=0, end=len("Python experience required")),
        ),
    )

    metadata = LLMAssessmentMetadata(
        model_identifier="llama3:8b",
        prompt_version="v1",
        context_strategy=ContextStrategy.JSON,
        model_digest="sha256:" + "d" * 64,
        prompt_fingerprint="sha256:" + "p" * 64,
        generation_call_id=uuid.uuid4(),
        generation_settings={"temperature": 0.0},
        token_usage=TokenUsage(prompt_tokens=150, completion_tokens=75, total_tokens=225),
    )

    return Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        policy_version="pol-1.0",
        assessment_method=AssessmentMethod.LLM,
        rule_outcomes=[
            RuleOutcome(
                criterion_id="work-auth",
                criterion_name="Work Authorization",
                result=HardCriterionResult.PASS,
                reason="Candidate is authorized",
            )
        ],
        requirement_findings=[finding],
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        relevance_score=95.0,
        score_scale="0-100",
        identified_gaps=[],
        identified_unknowns=[],
        summary_reason="Eligible: Strong match on Python",
        final_disposition=AssessmentDisposition.ELIGIBLE,
        model_metadata=metadata,
        validation_issues=[
            ValidationIssue(
                field_path="findings",
                code="info_note",
                message="All citations verified",
                severity="warning",
            )
        ],
        assessment_input_fingerprint="sha256:" + "f" * 64,
        deterministic_trace_ref="sha256:" + "t" * 64,
    )


def test_serialize_and_deserialize_run_result_success():
    """M02-13: Success AssessmentRunResult cleanly serializes and round-trips via JSON."""
    assessment = make_test_assessment()
    run_result = AssessmentRunResult(
        status="success",
        assessment=assessment,
        input_fingerprint="sha256:" + "f" * 64,
        validation_issues=assessment.validation_issues,
    )

    data = serialize_run_result(run_result)
    assert isinstance(data, dict)
    assert data["status"] == "success"
    assert data["assessment"]["relevance_score"] == 95.0

    reloaded = deserialize_run_result(data)
    assert reloaded.status == "success"
    assert reloaded.assessment is not None
    assert reloaded.assessment.assessment_id == assessment.assessment_id
    assert reloaded.assessment.relevance_score == 95.0
    assert len(reloaded.assessment.requirement_findings) == 1
    assert reloaded.assessment.requirement_findings[0].status == FindingStatus.MATCH


def test_serialize_and_deserialize_run_result_pending():
    """M02-13: Pending AssessmentRunResult cleanly serializes and round-trips via JSON."""
    baseline = make_test_assessment()
    err = ClassifiedError.from_category(
        ErrorCategory.TRANSIENT_SERVICE,
        "Local model provider unavailable",
    )
    run_result = AssessmentRunResult(
        status="pending",
        assessment=None,
        input_fingerprint="sha256:" + "f" * 64,
        failed_stage="inference",
        error=err,
        retryable=True,
        deterministic_baseline=baseline,
        audit_references={"attempt_id": "att-1"},
    )

    json_str = serialize_run_result(run_result)
    reloaded = deserialize_run_result(json_str)

    assert reloaded.status == "pending"
    assert reloaded.assessment is None
    assert reloaded.failed_stage == "inference"
    assert reloaded.retryable is True
    assert reloaded.error is not None
    assert reloaded.error.category == ErrorCategory.TRANSIENT_SERVICE
    assert reloaded.deterministic_baseline is not None
    assert reloaded.deterministic_baseline.assessment_id == baseline.assessment_id


def test_assessment_sqlite_repository_roundtrip(tmp_path: Path):
    """M02-12: Complete LLM Assessment with findings and model metadata persists in SQLite."""
    db_path = tmp_path / "llm_assessment_test.db"
    raw_dir = tmp_path / "raw"
    artifacts_dir = tmp_path / "artifacts"
    engine = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=artifacts_dir)
    engine.initialize_schema()

    assessment = make_test_assessment()

    # Create canonical job entry for foreign key / association
    now_dt = datetime.now(timezone.utc)
    canonical_job = CanonicalJob(
        canonical_job_id=assessment.canonical_job_id,
        company_name="Tech Corp",
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_dt,
        last_seen_at=now_dt,
    )
    engine.canonical_jobs.save_canonical_job(canonical_job)

    # Save LLM assessment
    engine.assessments.save_assessment(assessment)

    # Load and verify
    loaded = engine.assessments.get_assessment(assessment.assessment_id)
    assert loaded is not None
    assert loaded.assessment_id == assessment.assessment_id
    assert loaded.canonical_job_id == assessment.canonical_job_id
    assert loaded.assessment_method == AssessmentMethod.LLM
    assert loaded.final_disposition == AssessmentDisposition.ELIGIBLE
    assert loaded.relevance_score == 95.0
    assert loaded.model_metadata is not None
    assert loaded.model_metadata.model_identifier == "llama3:8b"
    assert len(loaded.requirement_findings) == 1
    assert loaded.requirement_findings[0].requirement_id == "req-1"

    engine.close()


def test_legacy_assessor_adapter_behavior():
    """Legacy Assessor adapter implements Assessor protocol and fails visibly when unbound."""
    from job_automation.assessment.errors import AssessmentInputError
    from job_automation.contracts.identity import PostingRevision

    mock_v2_service = MagicMock()
    adapter = LegacyAssessorAdapter(v2_service=mock_v2_service)

    now_dt = datetime.now(timezone.utc)
    posting_rev = PostingRevision(
        revision_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p-1"),
        content_hash="sha256:" + "d" * 64,
        title="Python Engineer",
        first_seen_at=now_dt,
        last_seen_at=now_dt,
    )
    bundle = ContextBundle(
        strategy=ContextStrategy.JSON,
        purpose="assessment",
        posting_revision=posting_rev.content_hash,
        profile_version="v1",
        token_budget=2000,
        estimated_tokens=100,
    )

    with pytest.raises(AssessmentInputError) as exc_info:
        adapter.assess(
            rule_outcomes=[],
            revision=posting_rev,
            context=bundle,
        )

    assert "Use AssessorV2 with AssessmentRequest" in str(exc_info.value)
