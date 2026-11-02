"""Tests for version history tracking and structural diff calculation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.profile.history import compare_snapshots


class TestProfileHistory:
    def test_compare_snapshots_diff_classification(self) -> None:
        cid = uuid.uuid4()
        now = datetime.now(timezone.utc)

        f_common_id = uuid.uuid4()
        f_updated_id = uuid.uuid4()
        f_removed_id = uuid.uuid4()
        f_added_id = uuid.uuid4()

        snap_v1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(is_approved=True, approved_by="candidate", approved_at=now),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[
                CandidateFact(fact_id=f_common_id, kind=EvidenceFactKind.SKILL, title="Python", provenance="v1"),
                CandidateFact(fact_id=f_updated_id, kind=EvidenceFactKind.EMPLOYMENT, title="Engineer", claims=["Old claim"], provenance="v1"),
                CandidateFact(fact_id=f_removed_id, kind=EvidenceFactKind.PROJECT, title="Old Project", provenance="v1"),
            ],
        )

        snap_v2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2",
            approval_metadata=ProfileApprovalMetadata(is_approved=True, approved_by="candidate", approved_at=now),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE", "AT"]),
            evidence_records=[
                CandidateFact(fact_id=f_common_id, kind=EvidenceFactKind.SKILL, title="Python", provenance="v1"),
                CandidateFact(fact_id=f_updated_id, kind=EvidenceFactKind.EMPLOYMENT, title="Senior Engineer", claims=["New claim"], provenance="v2"),
                CandidateFact(fact_id=f_added_id, kind=EvidenceFactKind.CERTIFICATION, title="AWS Certified", provenance="v2"),
            ],
        )

        diff = compare_snapshots(snap_v1, snap_v2)
        assert diff.base_version == "v1"
        assert diff.target_version == "v2"

        # Added
        assert len(diff.added_facts) == 1
        assert diff.added_facts[0].fact_id == f_added_id

        # Removed
        assert len(diff.removed_facts) == 1
        assert diff.removed_facts[0].fact_id == f_removed_id

        # Updated
        assert len(diff.updated_facts) == 1
        assert diff.updated_facts[0].fact_id == f_updated_id
        assert "title" in diff.updated_facts[0].changed_fields
        assert "claims" in diff.updated_facts[0].changed_fields

        # Unchanged
        assert diff.unchanged_fact_ids == [f_common_id]

        # Eligibility
        assert diff.eligibility_changed is True

