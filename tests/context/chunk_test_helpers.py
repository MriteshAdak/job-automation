"""Shared helper functions and synthetic profile generators for CONTEXT-02 tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)


def make_approval(
    approved_by: str = "reviewer@example.com", notes: str = "Approved synthetic snapshot"
) -> ProfileApprovalMetadata:
    """Create valid ProfileApprovalMetadata."""
    return ProfileApprovalMetadata(
        is_approved=True,
        approved_by=approved_by,
        approved_at=datetime.now(timezone.utc),
        notes=notes,
    )


def create_minimal_snapshot(
    candidate_id: uuid.UUID | None = None,
    profile_version: str = "v1",
    evidence_records: list[CandidateFact] | None = None,
) -> ProfileSnapshot:
    """Create minimal valid ProfileSnapshot."""
    return ProfileSnapshot(
        candidate_id=candidate_id or uuid.uuid4(),
        profile_version=profile_version,
        approval_metadata=make_approval(),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE"],
            target_locations=["Berlin"],
            remote_eligible=True,
        ),
        evidence_records=evidence_records or [],
    )

