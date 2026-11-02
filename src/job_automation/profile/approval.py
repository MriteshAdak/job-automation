"""Approval logic to convert a reviewed DraftProfile into an immutable ProfileSnapshot."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from job_automation.contracts.profile import (
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.profile.errors import (
    ProfileApprovalError,
    ProfileConflictError,
)
from job_automation.profile.models import DraftProfile
from job_automation.profile.validation import validate_draft, validate_snapshot


def approve_draft_to_snapshot(
    draft: DraftProfile,
    expected_draft_digest: str,
    approved_by: str,
    new_version: str,
    notes: str | None = None,
    expected_base_version: str | None = None,
    approved_at: datetime | None = None,
) -> tuple[ProfileSnapshot, str]:
    """Validate review digest and construct an approved C01 ProfileSnapshot with content hash.

    Returns:
        tuple of (ProfileSnapshot, sha256_content_hash)
    """
    if not approved_by or not approved_by.strip():
        raise ProfileApprovalError("Approver identity ('approved_by') must be non-empty")

    # 1. Digest binding check
    current_digest = draft.compute_digest()
    if current_digest != expected_draft_digest:
        raise ProfileConflictError(
            f"Stale review detected: draft content digest ({current_digest}) does not match expected digest ({expected_draft_digest})"
        )

    # 2. Base version check
    if expected_base_version is not None and draft.base_profile_version != expected_base_version:
        raise ProfileConflictError(
            f"Base version conflict: draft is based on '{draft.base_profile_version}' but expected base is '{expected_base_version}'"
        )

    # 3. Invariant validation
    validate_draft(draft)

    approval_time = approved_at or datetime.now(timezone.utc)

    # 4. Map draft facts to CandidateFact records
    evidence_records: list[CandidateFact] = []
    for f in draft.facts:
        prov = f.provenance_summary or f.provenance_id or "unspecified"
        cf = CandidateFact(
            fact_id=f.fact_id,
            kind=f.kind,
            parent_id=f.parent_id,
            title=f.title,
            organization=f.organization,
            start_date=f.start_date,
            end_date=f.end_date,
            claims=list(f.claims),
            skills=list(f.skills),
            metrics=list(f.metrics),
            provenance=prov,
            allowed_uses=list(f.allowed_uses),
        )
        evidence_records.append(cf)

    approval_metadata = ProfileApprovalMetadata(
        is_approved=True,
        approved_by=approved_by.strip(),
        approved_at=approval_time,
        notes=notes or draft.notes,
    )

    snapshot = ProfileSnapshot(
        candidate_id=draft.candidate_id,
        profile_version=new_version,
        approval_metadata=approval_metadata,
        explicit_eligibility=draft.proposed_eligibility,
        evidence_records=evidence_records,
    )

    # 5. Snapshot validation
    validate_snapshot(snapshot)

    # Compute deterministic content hash of published snapshot
    raw_json = snapshot.model_dump_json()
    content_hash = f"sha256:{hashlib.sha256(raw_json.encode('utf-8')).hexdigest()}"

    return snapshot, content_hash

