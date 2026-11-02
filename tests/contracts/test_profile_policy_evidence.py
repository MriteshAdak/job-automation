"""Tests for C01 ProfileSnapshot, C02 SearchPolicy, and C08 EvidenceReference contracts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import (
    ContextStrategy,
    EvidenceFactKind,
)
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
    SourceSpan,
)
from job_automation.contracts.policy import (
    HardCriterion,
    PreferenceRule,
    RelevanceConfig,
    SearchPolicy,
)
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)


class TestProfilePolicyEvidence:
    def test_candidate_evidence_reference_valid_and_invalid(self) -> None:
        fact_id = uuid.uuid4()
        ref = CandidateEvidenceReference(profile_version="v1.0", fact_id=fact_id)
        assert ref.source_kind == "candidate"
        assert ref.profile_version == "v1.0"
        assert ref.fact_id == fact_id

        # Missing profile_version
        with pytest.raises(ValidationError):
            CandidateEvidenceReference.model_validate({"fact_id": str(fact_id)})

    def test_job_evidence_reference_requires_quotation_or_span(self) -> None:
        # Valid with quotation
        ref1 = JobEvidenceReference(
            posting_revision="rev-001",
            field_path="description",
            quotation="Must have 5+ years of Python experience",
        )
        assert ref1.quotation is not None
        assert ref1.source_span is None

        # Valid with span
        ref2 = JobEvidenceReference(
            posting_revision="rev-001",
            field_path="requirements",
            source_span=SourceSpan(start=10, end=45),
        )
        assert ref2.source_span is not None

        # Invalid: neither quotation nor span
        with pytest.raises(ValidationError, match="at least one of 'quotation' or 'source_span'"):
            JobEvidenceReference(
                posting_revision="rev-001",
                field_path="description",
            )

        # Invalid span: end <= start
        with pytest.raises(ValidationError, match="must be greater than start"):
            SourceSpan(start=10, end=10)

    def test_profile_snapshot_with_month_precision(self) -> None:
        candidate_id = uuid.uuid4()
        fact_id = uuid.uuid4()
        parent_id = uuid.uuid4()

        fact = CandidateFact(
            fact_id=fact_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            parent_id=parent_id,
            title="Senior Software Engineer",
            organization="Acme GmbH",
            start_date=PrecisionDate(value="2021-05", precision="month"),
            end_date=None,
            claims=["Led migration to microservices architecture"],
            skills=["Python", "Docker", "PostgreSQL"],
            metrics=["Reduced p99 latency by 40%"],
            provenance="cv_2024_import.pdf",
            allowed_uses=["cv", "cover_letter", "assessment"],
        )

        approval = ProfileApprovalMetadata(
            is_approved=True,
            approved_by="candidate_self",
            approved_at=datetime.now(timezone.utc),
            notes="Initial import verification",
        )

        eligibility = CandidateEligibility(
            work_authorization_countries=["DE", "AT"],
            target_locations=["Berlin", "Remote"],
            remote_eligible=True,
            language_proficiencies={"de": "C1", "en": "C2"},
        )

        snapshot = ProfileSnapshot(
            candidate_id=candidate_id,
            profile_version="v2026.1",
            approval_metadata=approval,
            explicit_eligibility=eligibility,
            evidence_records=[fact],
        )

        assert snapshot.profile_version == "v2026.1"
        assert len(snapshot.evidence_records) == 1
        assert snapshot.evidence_records[0].start_date.value == "2021-05"
        assert snapshot.evidence_records[0].start_date.precision == "month"

        # Round trip
        dumped = snapshot.model_dump()
        reloaded = ProfileSnapshot.model_validate(dumped)
        assert reloaded == snapshot

    def test_search_policy_and_candidate_separation(self) -> None:
        policy = SearchPolicy(
            policy_version="policy-de-v1",
            regions=["DE"],
            role_aliases={"Software Engineer": ["Backend Developer", "Python Engineer"]},
            hard_criteria=[
                HardCriterion(
                    criterion_id="crit_location",
                    name="Location in Germany or Remote",
                    field="workplace_type",
                    operator="in",
                    expected_value=["remote", "hybrid", "onsite"],
                    on_missing="unknown",
                )
            ],
            preferences=[
                PreferenceRule(
                    rule_id="pref_python",
                    name="Prefers Python ecosystem",
                    field="skills",
                    weight=0.8,
                    preferred_values=["Python", "FastAPI"],
                )
            ],
            primary_context_strategy=ContextStrategy.RAG,
        )

        assert policy.primary_context_strategy == ContextStrategy.RAG

        # Invalid strategy fails
        with pytest.raises(ValidationError):
            SearchPolicy.model_validate(
                {"policy_version": "v1", "primary_context_strategy": "automatic-agent"}
            )

