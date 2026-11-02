"""Durable identity review case management and decision recording."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.primitives import SourceKey
from job_automation.identity.errors import InvalidOperationError, ReviewCaseNotFoundError
from job_automation.identity.models import ReviewCase

if TYPE_CHECKING:
    from job_automation.storage.repositories.canonical_jobs import CanonicalJobRepository
    from job_automation.storage.repositories.identity import IdentityRepository


def create_review_case(
    candidate_job_ids: list[uuid.UUID],
    source_key: SourceKey,
    reason: str,
    evidence: dict[str, Any],
    identity_repo: IdentityRepository,
) -> ReviewCase:
    """Create or return existing pending review case for this candidate pair."""
    # Deduplicate against existing pending cases
    for cid in candidate_job_ids:
        existing = identity_repo.find_pending_review_case(source_key, cid)
        if existing:
            return ReviewCase.model_validate(existing)

    case_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    case = ReviewCase(
        case_id=case_id,
        status="pending",
        reason=reason,
        candidate_job_ids=candidate_job_ids,
        source_key=source_key,
        evidence=evidence,
        created_at=now,
        updated_at=now,
    )
    identity_repo.save_review_case(
        case_id=case.case_id,
        status=case.status,
        reason=case.reason,
        candidate_job_ids=case.candidate_job_ids,
        source_key=case.source_key,
        evidence=case.evidence,
    )
    return case


def decide_review_case(
    case_id: str,
    decision: str,
    actor: str,
    reason: str,
    identity_repo: IdentityRepository,
    canonical_repo: CanonicalJobRepository | None = None,
) -> ReviewCase:
    """Record an operator decision ('accept', 'reject', 'defer') on a review case."""
    valid_decisions = ("accept", "reject", "defer")
    if decision not in valid_decisions:
        raise InvalidOperationError(
            f"Invalid decision '{decision}'. Must be one of: {valid_decisions}"
        )

    case_dict = identity_repo.get_review_case(case_id)
    if not case_dict:
        raise ReviewCaseNotFoundError(f"Review case '{case_id}' not found")

    case = ReviewCase.model_validate(case_dict)
    now = datetime.now(timezone.utc)

    # Map decision verb to status
    new_status = {
        "accept": "accepted",
        "reject": "rejected",
        "defer": "deferred",
    }[decision]

    identity_repo.update_review_case_status(
        case_id=case_id,
        status=new_status,
        actor=actor,
        reason=reason,
        decided_at=now,
    )

    return case.model_copy(
        update={
            "status": new_status,
            "decision_actor": actor,
            "decision_reason": reason,
            "decided_at": now,
            "updated_at": now,
        }
    )


def list_review_cases(
    identity_repo: IdentityRepository,
    status: str | None = None,
) -> list[ReviewCase]:
    """List review cases ordered by creation timestamp."""
    items = identity_repo.list_review_cases(status=status)
    return [ReviewCase.model_validate(item) for item in items]

