"""Tests for purpose-aware inclusion rules, parent privacy boundaries, and JSON/RAG consumer parity."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.profile.errors import (
    InclusionConflictError,
    ProfileValidationError,
)
from job_automation.profile.inclusion import InclusionRules
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine
from tests.fakes.profile_consumers import (
    FakeJsonContextConsumer,
    FakeRagContextConsumer,
)


class TestProfileInclusion:
    @pytest.fixture
    def sample_snapshot(self) -> ProfileSnapshot:
        cid = uuid.uuid4()
        now = datetime.now(timezone.utc)

        f_parent = uuid.uuid4()
        f_child = uuid.uuid4()
        f_assessment_only = uuid.uuid4()
        f_private = uuid.uuid4()

        facts = [
            CandidateFact(
                fact_id=f_parent,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Company Role (Restricted for Assessment)",
                provenance="test",
                allowed_uses=["cv"],  # Allowed for cv, NOT for assessment
            ),
            CandidateFact(
                fact_id=f_child,
                parent_id=f_parent,
                kind=EvidenceFactKind.PROJECT,
                title="Child Project (Allowed for Assessment)",
                claims=["Developed search component"],
                skills=["Python"],
                provenance="test",
                allowed_uses=["assessment", "cv"],
            ),
            CandidateFact(
                fact_id=f_assessment_only,
                kind=EvidenceFactKind.SKILL,
                title="Assessment Only Skill",
                skills=["Docker"],
                provenance="test",
                allowed_uses=["assessment"],
            ),
            CandidateFact(
                fact_id=f_private,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Private Historical Role",
                claims=["SECRET_CLAIM_MARKER"],
                provenance="test",
                allowed_uses=[],  # Private: excluded from all downstream uses
            ),
        ]

        return ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=facts,
        )

    def test_purpose_matrix_filtering(self, sample_snapshot: ProfileSnapshot) -> None:
        rules = InclusionRules()

        # Assessment view
        view_assess = rules.evaluate_inclusion(sample_snapshot, purpose="assessment")
        assess_fids = set(view_assess.eligible_fact_ids)

        # f_child and f_assessment_only have 'assessment' in allowed_uses
        # f_parent does not, f_private does not
        assert sample_snapshot.evidence_records[1].fact_id in assess_fids
        assert sample_snapshot.evidence_records[2].fact_id in assess_fids
        assert sample_snapshot.evidence_records[0].fact_id not in assess_fids
        assert sample_snapshot.evidence_records[3].fact_id not in assess_fids

        # Private role was excluded and SECRET_CLAIM_MARKER is absent
        assert view_assess.excluded_fact_count == 2
        for f in view_assess.eligible_facts:
            assert "SECRET_CLAIM_MARKER" not in f.claims

        # CV view
        view_cv = rules.evaluate_inclusion(sample_snapshot, purpose="cv")
        cv_fids = set(view_cv.eligible_fact_ids)
        assert sample_snapshot.evidence_records[0].fact_id in cv_fids
        assert sample_snapshot.evidence_records[1].fact_id in cv_fids
        assert sample_snapshot.evidence_records[2].fact_id not in cv_fids

    def test_unsupported_purpose_rejected(self, sample_snapshot: ProfileSnapshot) -> None:
        rules = InclusionRules()
        with pytest.raises(ProfileValidationError, match="Unsupported inclusion purpose"):
            rules.evaluate_inclusion(sample_snapshot, purpose="automatic_application")

    def test_mandatory_parent_conflict(self, sample_snapshot: ProfileSnapshot) -> None:
        rules = InclusionRules()
        parent_id = sample_snapshot.evidence_records[0].fact_id

        # If parent_id is designated as mandatory context, but restricted from assessment:
        with pytest.raises(InclusionConflictError, match="Mandatory .* is restricted"):
            rules.evaluate_inclusion(
                sample_snapshot,
                purpose="assessment",
                mandatory_fact_ids=[parent_id],
            )

    def test_json_and_rag_consumer_parity(self, tmp_path: Path, sample_snapshot: ProfileSnapshot) -> None:
        db_path = tmp_path / "parity_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            engine.profiles.publish_snapshot(
                snapshot=sample_snapshot,
                version_sequence=1,
                predecessor_version=None,
                content_hash="sha256:dummy",
                approved_by="candidate",
                approved_at=sample_snapshot.approval_metadata.approved_at,
            )
            service = ProfileService.from_engine(engine)

            json_consumer = FakeJsonContextConsumer(service)
            rag_consumer = FakeRagContextConsumer(service)

            json_bundle = json_consumer.build_context(sample_snapshot, purpose="assessment")
            rag_bundle = rag_consumer.build_index_and_retrieve(sample_snapshot, purpose="assessment")

            # 1. Both see the EXACT same list of eligible fact UUIDs
            assert json_bundle["eligible_fact_ids"] == rag_bundle["eligible_fact_ids"]
            assert json_bundle["excluded_count"] == rag_bundle["excluded_count"]
            assert json_bundle["eligibility"] == rag_bundle["eligibility"]

            # 2. Excluded facts (like f_private with SECRET_CLAIM_MARKER) do NOT appear in either
            json_claims = [c for f in json_bundle["facts"] for c in f.get("claims", [])]
            rag_texts = [c["text"] for c in rag_bundle["chunks"]]

            assert not any("SECRET_CLAIM_MARKER" in c for c in json_claims)
            assert not any("SECRET_CLAIM_MARKER" in t for t in rag_texts)
