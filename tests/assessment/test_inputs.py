"""Tests for input binding, privacy invariants, and validation (MATCH-01-S02)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.assessment.errors import AssessmentInputError
from job_automation.assessment.inputs import bind_assessment_input
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact


class TestInputs:
    def test_bind_valid_assessment_input(self, make_posting, make_profile, make_policy) -> None:
        posting = make_posting()
        profile = make_profile()
        policy = make_policy()

        inp = bind_assessment_input(
            canonical_job_id=uuid.uuid4(),
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )

        assert inp.profile_version == profile.profile_version
        assert inp.posting_revision == posting.raw_content_hash
        assert len(inp.permitted_facts) == 1
        assert inp.permitted_facts[0].title == "Senior Python Developer"

    def test_unapproved_profile_is_rejected(self, make_posting, make_profile, make_policy) -> None:
        posting = make_posting()
        unapproved = make_profile(is_approved=False)
        policy = make_policy()

        with pytest.raises(AssessmentInputError, match="not approved for use"):
            bind_assessment_input(
                canonical_job_id=uuid.uuid4(),
                posting_revision=posting.raw_content_hash,
                posting=posting,
                policy=policy,
                profile=unapproved,
            )

    def test_privacy_inclusion_filters_non_assessment_facts(
        self, make_posting, make_profile, make_policy
    ) -> None:
        """Facts tagged allowed_uses=['cv'] must NOT enter assessment input."""
        fact_public = CandidateFact(
            fact_id=uuid.uuid4(),
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Public Fact",
            start_date=PrecisionDate(value="2021", precision="year"),
            claims=["Allowed in assessment"],
            provenance="test",
            allowed_uses=["assessment"],
        )
        fact_private = CandidateFact(
            fact_id=uuid.uuid4(),
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Private CV Fact",
            start_date=PrecisionDate(value="2019", precision="year"),
            claims=["Secret project only for CV"],
            provenance="test",
            allowed_uses=["cv"],  # Excluded from assessment!
        )

        profile = make_profile(facts=[fact_public, fact_private])
        posting = make_posting()
        policy = make_policy()

        inp = bind_assessment_input(
            canonical_job_id=uuid.uuid4(),
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )

        assert len(inp.permitted_facts) == 1
        assert inp.permitted_facts[0].title == "Public Fact"
        assert all(f.title != "Private CV Fact" for f in inp.permitted_facts)

    def test_missing_profile_version_without_snapshot_raises(self, make_posting, make_policy) -> None:
        posting = make_posting()
        policy = make_policy()

        with pytest.raises(AssessmentInputError, match="profile_version must be provided"):
            bind_assessment_input(
                canonical_job_id=uuid.uuid4(),
                posting_revision=posting.raw_content_hash,
                posting=posting,
                policy=policy,
                profile=None,
                profile_version=None,
            )
