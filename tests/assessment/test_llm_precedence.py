"""Tests for authoritative deterministic precedence and disposition hierarchy (M02-08)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.assessment.llm_composition import compose_llm_assessment
from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentProposal,
    AssessmentRequest,
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
    WorkplaceType,
)
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference, SourceSpan
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from tests.context.selector_test_helpers import create_selector_test_snapshot


def make_test_fixture(
    baseline_disposition: AssessmentDisposition = AssessmentDisposition.ELIGIBLE,
    confirmed_hard_failures: list[str] | None = None,
    missing_data_rejections: list[str] | None = None,
    factual_unknowns: list[str] | None = None,
    eligibility_unknowns: list[str] | None = None,
    exclusion_rejections: list[str] | None = None,
):
    job_id = uuid.uuid4()
    posting_rev = "sha256:" + "8" * 64
    snapshot = create_selector_test_snapshot()
    fact1 = snapshot.evidence_records[0]

    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p-prec"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash=posting_rev,
        company_name_hint="Tech Corp",
        title="Python Engineer",
        description_clean="Python required",
        source_url="https://example.com/job/prec",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(timezone.utc),
    )

    policy = SearchPolicy(policy_version="pol-1.0")

    baseline_rules = [
        RuleOutcome(
            criterion_id="work-auth",
            criterion_name="Work Authorization",
            result=HardCriterionResult.FAIL if confirmed_hard_failures else HardCriterionResult.PASS,
            reason="Confirmed hard failure" if confirmed_hard_failures else "Authorized",
        )
    ]

    baseline = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        policy_version="pol-1.0",
        assessment_method=AssessmentMethod.RULES,
        relevance_decision=baseline_disposition,
        final_disposition=baseline_disposition,
        rule_outcomes=baseline_rules,
        summary_reason="Baseline deterministic assessment",
    )

    trace = DeterministicDecisionTrace(
        confirmed_hard_failures=confirmed_hard_failures or [],
        missing_data_rejections=missing_data_rejections or [],
        factual_unknowns=factual_unknowns or [],
        eligibility_unknowns=eligibility_unknowns or [],
        exclusion_rejections=exclusion_rejections or [],
    )

    request = AssessmentRequest(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        posting=posting,
        profile=snapshot,
        policy=policy,
        context_strategy=ContextStrategy.JSON,
        deterministic_baseline=baseline,
        deterministic_trace=trace,
        limits=AssessmentLimits(),
    )

    req1 = RequirementItem(
        requirement_id="req-1",
        text="Python required",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="description_clean",
            quotation="Python required",
            source_span=SourceSpan(start=0, end=len("Python required")),
        ),
    )
    req_set = RequirementSet(
        canonical_job_id=job_id,
        job_revision=posting_rev,
        requirements=[req1],
        fingerprint="sha256:" + "0" * 64,
        extractor_version="1.0",
    )

    metadata = LLMAssessmentMetadata(
        model_identifier="test-model",
        prompt_version="v1",
        context_strategy=ContextStrategy.JSON,
        model_digest="sha256:" + "m" * 64,
        prompt_fingerprint="sha256:" + "p" * 64,
        generation_call_id=uuid.uuid4(),
        generation_settings={},
    )

    return request, req_set, snapshot, metadata, fact1


def test_confirmed_hard_failure_preserves_rejected_despite_model_score_100():
    """M02-08: Model score 100 cannot override a confirmed hard failure."""
    request, req_set, snapshot, metadata, fact1 = make_test_fixture(
        baseline_disposition=AssessmentDisposition.REJECTED,
        confirmed_hard_failures=["work_authorization_failed"],
    )

    finding = RequirementFinding(
        requirement_id="req-1",
        requirement_text="Python required",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        status=FindingStatus.MATCH,
        reason="Has Python",
        score=100.0,
        candidate_evidence=[
            CandidateEvidenceReference(profile_version=snapshot.profile_version, fact_id=fact1.fact_id)
        ],
        job_evidence=req_set.requirements[0].job_evidence,
    )

    proposal = AssessmentProposal(
        relevance_score=100.0,
        score_scale="0-100",
        summary_reason="Perfect candidate",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-1",
                status=FindingStatus.MATCH,
                reason="Has Python",
                score=100.0,
            )
        ],
    )

    result = compose_llm_assessment(
        request=request,
        requirement_set=req_set,
        validated_findings=[finding],
        validation_issues=[],
        proposal=proposal,
        llm_metadata=metadata,
        input_fingerprint="sha256:fp",
    )

    assert result.final_disposition == AssessmentDisposition.REJECTED
    assert result.rule_outcomes[0].result == HardCriterionResult.FAIL


def test_missing_data_policy_rejection_preserves_rejected():
    """M02-08: on_missing='fail' policy rejection remains REJECTED."""
    request, req_set, snapshot, metadata, fact1 = make_test_fixture(
        baseline_disposition=AssessmentDisposition.REJECTED,
        missing_data_rejections=["salary_unspecified"],
    )

    finding = RequirementFinding(
        requirement_id="req-1",
        requirement_text="Python required",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        status=FindingStatus.MATCH,
        reason="Has Python",
        score=95.0,
        candidate_evidence=[
            CandidateEvidenceReference(profile_version=snapshot.profile_version, fact_id=fact1.fact_id)
        ],
        job_evidence=req_set.requirements[0].job_evidence,
    )

    proposal = AssessmentProposal(
        relevance_score=95.0,
        score_scale="0-100",
        summary_reason="Excellent candidate",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-1",
                status=FindingStatus.MATCH,
                reason="Has Python",
            )
        ],
    )

    result = compose_llm_assessment(
        request=request,
        requirement_set=req_set,
        validated_findings=[finding],
        validation_issues=[],
        proposal=proposal,
        llm_metadata=metadata,
        input_fingerprint="sha256:fp",
    )

    assert result.final_disposition == AssessmentDisposition.REJECTED


def test_unresolved_factual_unknown_preserves_review():
    """M02-08: Factual unknown produces REVIEW despite high model score."""
    request, req_set, snapshot, metadata, fact1 = make_test_fixture(
        baseline_disposition=AssessmentDisposition.REVIEW,
        factual_unknowns=["german_proficiency_unknown"],
    )

    finding = RequirementFinding(
        requirement_id="req-1",
        requirement_text="Python required",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        status=FindingStatus.MATCH,
        reason="Has Python",
        score=90.0,
        candidate_evidence=[
            CandidateEvidenceReference(profile_version=snapshot.profile_version, fact_id=fact1.fact_id)
        ],
        job_evidence=req_set.requirements[0].job_evidence,
    )

    proposal = AssessmentProposal(
        relevance_score=90.0,
        score_scale="0-100",
        summary_reason="High fit",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-1",
                status=FindingStatus.MATCH,
                reason="Has Python",
            )
        ],
    )

    result = compose_llm_assessment(
        request=request,
        requirement_set=req_set,
        validated_findings=[finding],
        validation_issues=[],
        proposal=proposal,
        llm_metadata=metadata,
        input_fingerprint="sha256:fp",
    )

    assert result.final_disposition == AssessmentDisposition.REVIEW


def test_confirmed_gap_on_required_requirement_produces_rejected():
    """M02-08: A confirmed gap on a REQUIRED requirement results in REJECTED."""
    request, req_set, snapshot, metadata, _ = make_test_fixture(
        baseline_disposition=AssessmentDisposition.ELIGIBLE,
    )

    finding = RequirementFinding(
        requirement_id="req-1",
        requirement_text="Python required",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        status=FindingStatus.GAP,
        reason="Candidate lacks Python experience",
        job_evidence=req_set.requirements[0].job_evidence,
    )

    proposal = AssessmentProposal(
        relevance_score=20.0,
        score_scale="0-100",
        summary_reason="Missing core requirement",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-1",
                status=FindingStatus.GAP,
                reason="Lacks Python",
            )
        ],
    )

    result = compose_llm_assessment(
        request=request,
        requirement_set=req_set,
        validated_findings=[finding],
        validation_issues=[],
        proposal=proposal,
        llm_metadata=metadata,
        input_fingerprint="sha256:fp",
    )

    assert result.final_disposition == AssessmentDisposition.REJECTED


def test_eligible_when_all_match_and_no_failures():
    """M02-08: Eligible candidate with matching findings and no failures produces ELIGIBLE."""
    request, req_set, snapshot, metadata, fact1 = make_test_fixture(
        baseline_disposition=AssessmentDisposition.ELIGIBLE,
    )

    finding = RequirementFinding(
        requirement_id="req-1",
        requirement_text="Python required",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        status=FindingStatus.MATCH,
        reason="Has Python",
        score=95.0,
        candidate_evidence=[
            CandidateEvidenceReference(profile_version=snapshot.profile_version, fact_id=fact1.fact_id)
        ],
        job_evidence=req_set.requirements[0].job_evidence,
    )

    proposal = AssessmentProposal(
        relevance_score=95.0,
        score_scale="0-100",
        summary_reason="Full match",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-1",
                status=FindingStatus.MATCH,
                reason="Has Python",
            )
        ],
    )

    result = compose_llm_assessment(
        request=request,
        requirement_set=req_set,
        validated_findings=[finding],
        validation_issues=[],
        proposal=proposal,
        llm_metadata=metadata,
        input_fingerprint="sha256:fp",
    )

    assert result.final_disposition == AssessmentDisposition.ELIGIBLE
    assert result.relevance_decision == AssessmentDisposition.ELIGIBLE
