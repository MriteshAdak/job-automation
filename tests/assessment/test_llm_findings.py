"""Tests for model proposal finding validation into typed RequirementFindings (M02-06, M02-10)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.assessment.finding_validation import validate_proposal_findings
from job_automation.assessment.llm_records import (
    AssessmentProposal,
    FindingStatus,
    RequirementFindingProposal,
    RequirementItem,
    RequirementObligation,
    RequirementSet,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import ContextStrategy, EvidenceFactKind, WorkplaceType
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
    SourceSpan,
)
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import CandidateFact
from tests.context.selector_test_helpers import create_selector_test_snapshot


def make_test_environment():
    posting_rev = "sha256:" + "f" * 64
    posting_text = "Senior Python Engineer needed. German C1 required. React experience nice to have."
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p-findings"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash=posting_rev,
        company_name_hint="Tech Corp",
        title="Senior Python Engineer",
        description_clean=posting_text,
        source_url="https://example.com/job/findings",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(timezone.utc),
    )

    snapshot = create_selector_test_snapshot()
    fact1 = snapshot.evidence_records[0]
    fact2 = snapshot.evidence_records[1]

    bundle = ContextBundle(
        strategy=ContextStrategy.JSON,
        purpose="assessment",
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        selected_fact_ids=[fact1.fact_id, fact2.fact_id],
        token_budget=2000,
        estimated_tokens=100,
    )

    req1 = RequirementItem(
        requirement_id="req-py",
        text="Senior Python Engineer needed",
        obligation=RequirementObligation.REQUIRED,
        category="skill",
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="description_clean",
            quotation="Senior Python Engineer needed",
            source_span=SourceSpan(start=0, end=len("Senior Python Engineer needed")),
        ),
    )
    req2 = RequirementItem(
        requirement_id="req-de",
        text="German C1 required",
        obligation=RequirementObligation.REQUIRED,
        category="language",
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="description_clean",
            quotation="German C1 required",
            source_span=SourceSpan(
                start=posting_text.index("German C1 required"),
                end=posting_text.index("German C1 required") + len("German C1 required"),
            ),
        ),
    )
    req3 = RequirementItem(
        requirement_id="req-react",
        text="React experience nice to have",
        obligation=RequirementObligation.PREFERRED,
        category="skill",
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="description_clean",
            quotation="React experience nice to have",
            source_span=SourceSpan(
                start=posting_text.index("React experience nice to have"),
                end=posting_text.index("React experience nice to have") + len("React experience nice to have"),
            ),
        ),
    )

    req_set = RequirementSet(
        canonical_job_id=uuid.uuid4(),
        job_revision=posting_rev,
        requirements=[req1, req2, req3],
        fingerprint="sha256:" + "0" * 64,
        extractor_version="1.0",
    )

    return posting, posting_rev, snapshot, bundle, req_set, fact1, fact2


def test_valid_proposal_findings():
    posting, posting_rev, snapshot, bundle, req_set, fact1, _ = make_test_environment()

    proposal = AssessmentProposal(
        relevance_score=85.0,
        score_scale="0-100",
        summary_reason="Strong candidate with Python expertise and German qualification.",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-py",
                status=FindingStatus.MATCH,
                reason="Demonstrated Python expertise",
                score=90.0,
                candidate_evidence=[
                    CandidateEvidenceReference(
                        profile_version=snapshot.profile_version,
                        fact_id=fact1.fact_id,
                    )
                ],
            ),
            RequirementFindingProposal(
                requirement_id="req-de",
                status=FindingStatus.GAP,
                reason="No C1 German certification",
            ),
            RequirementFindingProposal(
                requirement_id="req-react",
                status=FindingStatus.UNKNOWN,
                reason="Unspecified React skills",
            ),
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal,
        requirement_set=req_set,
        profile=snapshot,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle,
    )

    assert not issues, f"Expected no issues, got: {issues}"
    assert len(findings) == 3
    assert findings[0].status == FindingStatus.MATCH
    assert len(findings[0].candidate_evidence) == 1
    assert findings[1].status == FindingStatus.GAP
    assert findings[2].status == FindingStatus.UNKNOWN


def test_model_invents_unknown_requirement_id():
    posting, posting_rev, snapshot, bundle, req_set, fact1, _ = make_test_environment()

    proposal = AssessmentProposal(
        summary_reason="Test synthesis",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-py",
                status=FindingStatus.MATCH,
                reason="Matches Python",
                candidate_evidence=[
                    CandidateEvidenceReference(
                        profile_version=snapshot.profile_version,
                        fact_id=fact1.fact_id,
                    )
                ],
            ),
            RequirementFindingProposal(
                requirement_id="req-invented-xyz",
                status=FindingStatus.MATCH,
                reason="Invented finding",
                candidate_evidence=[
                    CandidateEvidenceReference(
                        profile_version=snapshot.profile_version,
                        fact_id=fact1.fact_id,
                    )
                ],
            ),
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal,
        requirement_set=req_set,
        profile=snapshot,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle,
    )

    assert any(i.code == "unknown_requirement_id" for i in issues)
    # The admitted requirements are 3, so findings should be 3 (one for req-py, plus two defaulted for req-de and req-react)
    assert len(findings) == 3
    assert not any(f.requirement_id == "req-invented-xyz" for f in findings)


def test_model_duplicate_findings_for_same_requirement():
    posting, posting_rev, snapshot, bundle, req_set, fact1, _ = make_test_environment()

    proposal = AssessmentProposal(
        summary_reason="Test synthesis",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-py",
                status=FindingStatus.MATCH,
                reason="Matches Python",
                candidate_evidence=[
                    CandidateEvidenceReference(
                        profile_version=snapshot.profile_version,
                        fact_id=fact1.fact_id,
                    )
                ],
            ),
            RequirementFindingProposal(
                requirement_id="req-py",
                status=FindingStatus.GAP,
                reason="Also claims gap",
            ),
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal,
        requirement_set=req_set,
        profile=snapshot,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle,
    )

    assert any(i.code == "duplicate_requirement_finding" for i in issues)


def test_model_omits_requirement_defaults_to_application_unknown():
    posting, posting_rev, snapshot, bundle, req_set, fact1, _ = make_test_environment()

    proposal = AssessmentProposal(
        summary_reason="Test synthesis",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-py",
                status=FindingStatus.MATCH,
                reason="Matches Python",
                candidate_evidence=[
                    CandidateEvidenceReference(
                        profile_version=snapshot.profile_version,
                        fact_id=fact1.fact_id,
                    )
                ],
            ),
            # req-de and req-react are omitted!
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal,
        requirement_set=req_set,
        profile=snapshot,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle,
    )

    assert any(i.code == "missing_requirement_coverage" for i in issues)
    assert len(findings) == 3
    assert findings[1].requirement_id == "req-de"
    assert findings[1].status == FindingStatus.UNKNOWN
    assert findings[2].requirement_id == "req-react"
    assert findings[2].status == FindingStatus.UNKNOWN


def test_match_missing_candidate_evidence_downgrades_to_unknown():
    posting, posting_rev, snapshot, bundle, req_set, _, _ = make_test_environment()

    proposal = AssessmentProposal(
        summary_reason="Test synthesis",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-py",
                status=FindingStatus.MATCH,
                reason="Claims match without evidence",
                candidate_evidence=[],  # Model claims MATCH but cites NO evidence!
            ),
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal,
        requirement_set=req_set,
        profile=snapshot,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle,
    )

    assert any(i.code == "match_missing_candidate_evidence" for i in issues)
    assert findings[0].status == FindingStatus.UNKNOWN


def test_unknown_with_candidate_evidence_flags_issue():
    posting, posting_rev, snapshot, bundle, req_set, fact1, _ = make_test_environment()

    proposal = AssessmentProposal(
        summary_reason="Test synthesis",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-react",
                status=FindingStatus.UNKNOWN,
                reason="Claims unknown but attaches evidence",
                candidate_evidence=[
                    CandidateEvidenceReference(
                        profile_version=snapshot.profile_version,
                        fact_id=fact1.fact_id,
                    )
                ],
            ),
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal,
        requirement_set=req_set,
        profile=snapshot,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle,
    )

    assert any(i.code == "invented_evidence_for_unknown" for i in issues)
    # The invalid evidence should be stripped from unknown
    assert len(findings[2].candidate_evidence) == 0


def test_semantic_contradiction_introductory_exposure_for_senior_c1():
    """Detects mechanical contradiction where candidate fact has 'introductory exposure only' but model claims MATCH for C1/senior (M02-06)."""
    posting, posting_rev, snapshot, bundle, req_set, _, _ = make_test_environment()

    contradictory_id = uuid.uuid4()
    contradictory_fact = CandidateFact(
        fact_id=contradictory_id,
        kind=EvidenceFactKind.SKILL,
        title="German Course",
        claims=["Completed introductory German course: introductory exposure only (Grundkenntnisse)"],
        skills=["German"],
        provenance="language-cert-2022",
    )
    records = list(snapshot.evidence_records) + [contradictory_fact]
    snapshot_with_limitation = snapshot.model_copy(update={"evidence_records": records})

    bundle_with_limitation = ContextBundle(
        strategy=ContextStrategy.JSON,
        purpose="assessment",
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        selected_fact_ids=[contradictory_id],
        token_budget=2000,
        estimated_tokens=100,
    )

    # Model proposes MATCH for C1 German citing this introductory fact!
    proposal = AssessmentProposal(
        relevance_score=85.0,
        score_scale="0-100",
        summary_reason="Candidate matches C1 German.",
        findings=[
            RequirementFindingProposal(
                requirement_id="req-de",
                status=FindingStatus.MATCH,
                reason="Has German course",
                candidate_evidence=[
                    CandidateEvidenceReference(
                        profile_version=snapshot.profile_version,
                        fact_id=contradictory_id,
                    )
                ],
            ),
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal,
        requirement_set=req_set,
        profile=snapshot_with_limitation,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle_with_limitation,
    )

    assert any(i.code == "semantic_contradiction" for i in issues)
