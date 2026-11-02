"""Tests for LLM assessment persistence across SQLite connection/process restarts (M02-14)."""

from __future__ import annotations

from pathlib import Path
import uuid
from datetime import datetime, timezone

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
    FindingStatus,
    HardCriterionResult,
    RequirementCategory,
    RequirementObligation,
)
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference, SourceSpan
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.models import TokenUsage
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import create_selector_test_snapshot


def test_llm_assessment_persists_across_engine_restarts(tmp_path: Path):
    """M02-14: Verification that LLM assessment with findings and metadata survives engine restart."""
    db_path = tmp_path / "restart_llm_test.db"
    raw_dir = tmp_path / "raw"
    art_dir = tmp_path / "artifacts"

    job_id = uuid.uuid4()
    assessment_id = uuid.uuid4()
    snapshot = create_selector_test_snapshot()
    fact1 = snapshot.evidence_records[0]

    # Session 1: Create, save, and close
    engine1 = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=art_dir)
    engine1.initialize_schema()

    canonical_job = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Cloud Tech AG",
        current_revision_id=uuid.uuid4(),
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    engine1.canonical_jobs.save_canonical_job(canonical_job)

    finding = RequirementFinding(
        requirement_id="req-py",
        requirement_text="Python expertise required",
        obligation=RequirementObligation.REQUIRED,
        category=RequirementCategory.SKILL,
        status=FindingStatus.MATCH,
        reason="Has 5+ years of Python",
        score=95.0,
        candidate_evidence=[
            CandidateEvidenceReference(
                profile_version=snapshot.profile_version,
                fact_id=fact1.fact_id,
            )
        ],
        job_evidence=JobEvidenceReference(
            posting_revision="sha256:" + "b" * 64,
            field_path="description_clean",
            quotation="Python expertise required",
            source_span=SourceSpan(start=0, end=len("Python expertise required")),
        ),
    )

    meta = LLMAssessmentMetadata(
        model_identifier="llama3:8b",
        prompt_version="v1",
        context_strategy=ContextStrategy.JSON,
        model_digest="sha256:" + "d" * 64,
        prompt_fingerprint="sha256:" + "p" * 64,
        generation_call_id=uuid.uuid4(),
        generation_settings={"temperature": 0.0},
        token_usage=TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300),
    )

    assessment = Assessment(
        assessment_id=assessment_id,
        canonical_job_id=job_id,
        posting_revision="sha256:" + "b" * 64,
        profile_version=snapshot.profile_version,
        policy_version="pol-1.0",
        assessment_method=AssessmentMethod.LLM,
        rule_outcomes=[
            RuleOutcome(
                criterion_id="work-auth",
                criterion_name="Work Authorization",
                result=HardCriterionResult.PASS,
                reason="Authorized",
            )
        ],
        requirement_findings=[finding],
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        relevance_score=95.0,
        score_scale="0-100",
        identified_gaps=[],
        identified_unknowns=[],
        summary_reason="Eligible: Complete Python match",
        final_disposition=AssessmentDisposition.ELIGIBLE,
        model_metadata=meta,
        validation_issues=[
            ValidationIssue(
                field_path="findings",
                code="info",
                message="Valid citation",
            )
        ],
        assessment_input_fingerprint="sha256:" + "f" * 64,
        deterministic_trace_ref="sha256:" + "t" * 64,
    )

    engine1.assessments.save_assessment(assessment)
    engine1.close()

    # Session 2: New engine instance reopens existing DB
    engine2 = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=art_dir)

    loaded = engine2.assessments.get_assessment(assessment_id)
    assert loaded is not None
    assert loaded.assessment_id == assessment_id
    assert loaded.canonical_job_id == job_id
    assert loaded.assessment_method == AssessmentMethod.LLM
    assert loaded.final_disposition == AssessmentDisposition.ELIGIBLE
    assert loaded.relevance_score == 95.0
    assert loaded.assessment_input_fingerprint == "sha256:" + "f" * 64
    assert loaded.deterministic_trace_ref == "sha256:" + "t" * 64

    # Verify model metadata persisted and deserialized
    assert loaded.model_metadata is not None
    assert loaded.model_metadata.model_identifier == "llama3:8b"
    assert loaded.model_metadata.context_strategy == ContextStrategy.JSON
    assert loaded.model_metadata.token_usage is not None
    assert loaded.model_metadata.token_usage.total_tokens == 300

    # Verify requirement findings persisted
    assert len(loaded.requirement_findings) == 1
    f = loaded.requirement_findings[0]
    assert f.requirement_id == "req-py"
    assert f.status == FindingStatus.MATCH
    assert len(f.candidate_evidence) == 1
    assert f.candidate_evidence[0].fact_id == fact1.fact_id

    engine2.close()

