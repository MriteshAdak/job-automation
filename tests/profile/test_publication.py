"""Tests for human approval binding, digest checks, and atomic snapshot publication."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.profile import CandidateEligibility
from job_automation.profile.approval import approve_draft_to_snapshot
from job_automation.profile.errors import (
    ProfileApprovalError,
    ProfileConflictError,
)
from job_automation.profile.models import DraftFact, DraftProfile
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine


class TestProfilePublication:
    def test_approve_draft_to_snapshot_success(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        now = datetime.now(timezone.utc)

        draft = DraftProfile(
            candidate_id=cid,
            proposed_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            facts=[
                DraftFact(
                    fact_id=fid,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Senior Python Engineer",
                    claims=["Architected pipeline"],
                    allowed_uses=["cv", "assessment"],
                )
            ],
            notes="Ready for review",
            created_at=now,
            updated_at=now,
        )
        digest = draft.compute_digest()

        snapshot, content_hash = approve_draft_to_snapshot(
            draft=draft,
            expected_draft_digest=digest,
            approved_by="candidate_self",
            new_version="v1",
            notes="Reviewed and approved",
        )

        assert snapshot.profile_version == "v1"
        assert snapshot.approval_metadata.is_approved is True
        assert snapshot.approval_metadata.approved_by == "candidate_self"
        assert len(snapshot.evidence_records) == 1
        assert snapshot.evidence_records[0].title == "Senior Python Engineer"
        assert content_hash.startswith("sha256:")

    def test_approve_with_stale_digest_fails(self) -> None:
        cid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        draft = DraftProfile(
            candidate_id=cid,
            proposed_eligibility=CandidateEligibility(),
            facts=[
                DraftFact(
                    fact_id=uuid.uuid4(),
                    kind=EvidenceFactKind.SKILL,
                    title="Python",
                )
            ],
            created_at=now,
            updated_at=now,
        )

        with pytest.raises(ProfileConflictError, match="Stale review detected"):
            approve_draft_to_snapshot(
                draft=draft,
                expected_draft_digest="sha256:different_or_stale_digest",
                approved_by="candidate",
                new_version="v1",
            )

    def test_approve_with_stale_base_version_fails(self) -> None:
        cid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        draft = DraftProfile(
            candidate_id=cid,
            base_profile_version="v1",
            proposed_eligibility=CandidateEligibility(),
            facts=[],
            created_at=now,
            updated_at=now,
        )
        digest = draft.compute_digest()

        with pytest.raises(ProfileConflictError, match="Base version conflict"):
            approve_draft_to_snapshot(
                draft=draft,
                expected_draft_digest=digest,
                approved_by="candidate",
                new_version="v2",
                expected_base_version="v0",  # Mismatched expected base
            )

    def test_empty_approver_rejected(self) -> None:
        cid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        draft = DraftProfile(
            candidate_id=cid,
            proposed_eligibility=CandidateEligibility(),
            facts=[],
            created_at=now,
            updated_at=now,
        )
        digest = draft.compute_digest()

        with pytest.raises(ProfileApprovalError, match="must be non-empty"):
            approve_draft_to_snapshot(
                draft=draft,
                expected_draft_digest=digest,
                approved_by="   ",
                new_version="v1",
            )

    def test_full_service_publication_and_version_progression(self, tmp_path: Path) -> None:
        db_path = tmp_path / "pub_service_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            service = ProfileService.from_engine(engine)

            # 1. Import Draft 1
            cid = uuid.uuid4()
            fid1 = uuid.uuid4()
            draft1 = service.import_draft(
                {
                    "candidate_id": str(cid),
                    "facts": [
                        {
                            "fact_id": str(fid1),
                            "title": "Engineer v1",
                            "kind": "employment",
                            "allowed_uses": ["cv"],
                        }
                    ],
                }
            )

            # 2. Approve Draft 1 -> v1
            snap1 = service.approve_and_publish(
                draft_id=draft1.draft_id,
                expected_draft_digest=draft1.content_digest,
                approved_by="candidate",
            )
            assert snap1.profile_version == "v1"
            assert service.get_current_snapshot(cid).profile_version == "v1"

            # 3. Import Draft 2 (correction to fid1, based on v1)
            draft2 = service.import_draft(
                {
                    "candidate_id": str(cid),
                    "base_profile_version": "v1",
                    "facts": [
                        {
                            "fact_id": str(fid1),
                            "title": "Senior Engineer v2",
                            "kind": "employment",
                            "allowed_uses": ["cv", "assessment"],
                        }
                    ],
                }
            )

            # 4. Approve Draft 2 -> v2
            snap2 = service.approve_and_publish(
                draft_id=draft2.draft_id,
                expected_draft_digest=draft2.content_digest,
                approved_by="candidate",
                expected_base_version="v1",
            )
            assert snap2.profile_version == "v2"
            assert service.get_current_snapshot(cid).profile_version == "v2"

            # 5. Check history shows both versions
            hist = service.list_history(cid)
            assert len(hist) == 2
            assert hist[0].profile_version == "v1"
            assert hist[0].is_current is False
            assert hist[1].profile_version == "v2"
            assert hist[1].is_current is True

