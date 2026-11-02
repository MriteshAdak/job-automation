"""Tests for exact citation resolution and evidence reference validation (M02-06, M02-10)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.assessment.reference_validation import (
    validate_candidate_reference,
    validate_job_reference,
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


def make_test_posting(text: str = "Wir suchen Softwareentwickler für moderne Cloud-Systeme.") -> tuple[NormalizedPosting, str]:
    rev = "sha256:" + "a" * 64
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p-evidence"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash=rev,
        company_name_hint="Tech Corp",
        title="Softwareentwickler",
        description_clean=text,
        source_url="https://example.com/job/evidence",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(timezone.utc),
    )
    return posting, rev


def make_test_bundle(selected_ids: list[uuid.UUID], profile_ver: str) -> ContextBundle:
    return ContextBundle(
        strategy=ContextStrategy.JSON,
        purpose="assessment",
        posting_revision="sha256:" + "a" * 64,
        profile_version=profile_ver,
        selected_fact_ids=selected_ids,
        token_budget=2000,
        estimated_tokens=100,
    )


def test_job_reference_valid_unicode_offsets():
    text = "Wir suchen Softwareentwickler für moderne Cloud-Systeme."
    posting, rev = make_test_posting(text)
    
    quote = "Softwareentwickler für moderne"
    start = text.index(quote)
    end = start + len(quote)

    ref = JobEvidenceReference(
        posting_revision=rev,
        field_path="description_clean",
        quotation=quote,
        source_span=SourceSpan(start=start, end=end),
    )

    issues = validate_job_reference(ref, posting, rev)
    assert not issues, f"Expected no issues, got: {issues}"


def test_job_reference_revision_mismatch():
    posting, rev = make_test_posting()
    ref = JobEvidenceReference(
        posting_revision="sha256:" + "b" * 64,
        field_path="description_clean",
        quotation="Softwareentwickler",
        source_span=SourceSpan(start=11, end=29),
    )
    issues = validate_job_reference(ref, posting, rev)
    assert any(i.code == "revision_mismatch" for i in issues)


def test_job_reference_invalid_field_path():
    posting, rev = make_test_posting()
    ref = JobEvidenceReference(
        posting_revision=rev,
        field_path="nonexistent_field",
        quotation="Softwareentwickler",
    )
    issues = validate_job_reference(ref, posting, rev)
    assert any(i.code == "invalid_field_path" for i in issues)


def test_job_reference_out_of_bounds_span():
    posting, rev = make_test_posting("Short text")
    ref = JobEvidenceReference(
        posting_revision=rev,
        field_path="description_clean",
        quotation="Short",
        source_span=SourceSpan(start=0, end=999),
    )
    issues = validate_job_reference(ref, posting, rev)
    assert any(i.code == "out_of_bounds_span" for i in issues)


def test_job_reference_quotation_not_found():
    posting, rev = make_test_posting("Python Backend Engineer")
    ref = JobEvidenceReference(
        posting_revision=rev,
        field_path="description_clean",
        quotation="Ruby on Rails",
    )
    issues = validate_job_reference(ref, posting, rev)
    assert any(i.code == "quotation_not_found" for i in issues)


def test_job_reference_quote_span_mismatch():
    text = "Wir suchen Softwareentwickler für moderne Cloud-Systeme."
    posting, rev = make_test_posting(text)
    
    # Span points to "Softwareentwickler", but quotation says "Cloud-Systeme"
    start = text.index("Softwareentwickler")
    end = start + len("Softwareentwickler")

    ref = JobEvidenceReference(
        posting_revision=rev,
        field_path="description_clean",
        quotation="Cloud-Systeme",
        source_span=SourceSpan(start=start, end=end),
    )
    issues = validate_job_reference(ref, posting, rev)
    assert any(i.code == "quote_span_mismatch" for i in issues)


def test_candidate_reference_valid():
    snapshot = create_selector_test_snapshot()
    fact = snapshot.evidence_records[0]
    bundle = make_test_bundle(selected_ids=[fact.fact_id], profile_ver=snapshot.profile_version)

    ref = CandidateEvidenceReference(
        profile_version=snapshot.profile_version,
        fact_id=fact.fact_id,
    )
    issues = validate_candidate_reference(ref, snapshot, bundle)
    assert not issues, f"Expected no issues, got: {issues}"


def test_candidate_reference_version_mismatch():
    snapshot = create_selector_test_snapshot()
    fact = snapshot.evidence_records[0]
    bundle = make_test_bundle(selected_ids=[fact.fact_id], profile_ver=snapshot.profile_version)

    ref = CandidateEvidenceReference(
        profile_version="v_wrong",
        fact_id=fact.fact_id,
    )
    issues = validate_candidate_reference(ref, snapshot, bundle)
    assert any(i.code == "profile_version_mismatch" for i in issues)


def test_candidate_reference_unknown_fact_id():
    snapshot = create_selector_test_snapshot()
    unknown_id = uuid.uuid4()
    bundle = make_test_bundle(selected_ids=[unknown_id], profile_ver=snapshot.profile_version)

    ref = CandidateEvidenceReference(
        profile_version=snapshot.profile_version,
        fact_id=unknown_id,
    )
    issues = validate_candidate_reference(ref, snapshot, bundle)
    assert any(i.code == "unknown_candidate_fact_id" for i in issues)


def test_candidate_reference_unselected_fact_rejected():
    """Fact exists in profile snapshot, but was NOT admitted into the bundle (M02-10)."""
    snapshot = create_selector_test_snapshot()
    assert len(snapshot.evidence_records) >= 2
    admitted_fact = snapshot.evidence_records[0]
    unselected_fact = snapshot.evidence_records[1]

    bundle = make_test_bundle(selected_ids=[admitted_fact.fact_id], profile_ver=snapshot.profile_version)

    ref = CandidateEvidenceReference(
        profile_version=snapshot.profile_version,
        fact_id=unselected_fact.fact_id,
    )
    issues = validate_candidate_reference(ref, snapshot, bundle)
    assert any(i.code == "unselected_fact_reference" for i in issues)


def test_candidate_reference_restricted_fact_rejected():
    """Fact is tagged as CV-only, not permitted for assessment (M02-04, M02-10)."""
    snapshot = create_selector_test_snapshot()
    restricted_id = uuid.uuid4()
    restricted_fact = CandidateFact(
        fact_id=restricted_id,
        kind=EvidenceFactKind.SKILL,
        title="Confidential Defense Project",
        provenance="internal-record",
        allowed_uses=["cv"],  # NOT allowed for assessment!
    )
    # Add restricted fact to snapshot
    updated_records = list(snapshot.evidence_records) + [restricted_fact]
    snapshot_with_restricted = snapshot.model_copy(update={"evidence_records": updated_records})

    bundle = make_test_bundle(selected_ids=[restricted_id], profile_ver=snapshot.profile_version)

    ref = CandidateEvidenceReference(
        profile_version=snapshot.profile_version,
        fact_id=restricted_id,
    )
    issues = validate_candidate_reference(ref, snapshot_with_restricted, bundle)
    assert any(i.code == "restricted_fact_reference" for i in issues)
