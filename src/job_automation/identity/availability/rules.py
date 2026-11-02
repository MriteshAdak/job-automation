"""Availability state transitions and repeated-miss / grace rules (IDENTITY-02-S04 & S05).

Rules:
- Reopen only from newer positive observations (advances last_seen_at, resets miss streak).
- Out-of-order or cached sightings older than last_seen_at cannot reopen or reset a streak.
- Transition to unavailable requires BOTH:
  1. consecutive_complete_misses threshold met (>= configured threshold, min 2)
  2. elapsed time from first qualifying miss >= grace_seconds.
- Zero grace still requires meeting the repeated miss threshold.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import UtcDatetime
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    SourcePostingAvailability,
)
from job_automation.identity.availability.settings import AvailabilityRuleSettings


def evaluate_sighting(
    current: SourcePostingAvailability,
    observed_at: datetime,
    policy_fingerprint: str,
    manifest_id: str | None = None,
    run_id: uuid.UUID | None = None,
) -> tuple[SourcePostingAvailability, AvailabilityDecision | None]:
    """Process a positive sighting for a source posting in a specific scope."""
    if observed_at < current.last_seen_at:
        # Older or cached observation delivered out of order: does not reopen or update
        return (current, None)

    updated_last_seen = max(current.last_seen_at, observed_at)

    if (
        current.availability != PostingAvailability.ACTIVE
        or current.miss_count > 0
        or current.missing_since is not None
    ):
        is_reopening = current.availability in (
            PostingAvailability.UNAVAILABLE,
            PostingAvailability.NOT_SEEN,
        )
        reason = "reopened_by_newer_sighting" if is_reopening else "sighting_observed"

        new_state = current.model_copy(
            update={
                "availability": PostingAvailability.ACTIVE,
                "last_seen_at": updated_last_seen,
                "missing_since": None,
                "miss_count": 0,
                "policy_fingerprint": policy_fingerprint,
            }
        )

        decision = AvailabilityDecision(
            source_key=current.source_key,
            canonical_job_id=current.canonical_job_id,
            scope_id=current.scope_id,
            manifest_id=manifest_id,
            run_id=run_id,
            from_availability=current.availability,
            to_availability=PostingAvailability.ACTIVE,
            reason=reason,
            miss_count=0,
            missing_since=None,
            event_time=observed_at,
            policy_fingerprint=policy_fingerprint,
        )
        return (new_state, decision)

    # Was already ACTIVE and clean; simply advance last_seen_at if newer
    new_state = current.model_copy(
        update={
            "last_seen_at": updated_last_seen,
            "policy_fingerprint": policy_fingerprint,
        }
    )
    return (new_state, None)


def evaluate_miss(
    current: SourcePostingAvailability,
    inventory_end: datetime,
    settings: AvailabilityRuleSettings,
    policy_fingerprint: str,
    manifest_id: str | None = None,
    run_id: uuid.UUID | None = None,
) -> tuple[SourcePostingAvailability, AvailabilityDecision]:
    """Evaluate a qualifying complete inventory miss against threshold and grace rules."""
    if current.availability in (PostingAvailability.ACTIVE, PostingAvailability.UNKNOWN):
        new_miss_count = 1
        new_missing_since = inventory_end
        new_availability = PostingAvailability.NOT_SEEN
        reason = "absent_from_complete_inventory_streak_1"

    elif current.availability == PostingAvailability.NOT_SEEN:
        new_miss_count = current.miss_count + 1
        new_missing_since = current.missing_since or inventory_end
        elapsed_seconds = (inventory_end - new_missing_since).total_seconds()

        threshold_met = new_miss_count >= settings.consecutive_complete_misses
        grace_met = elapsed_seconds >= settings.grace_seconds

        if threshold_met and grace_met:
            new_availability = PostingAvailability.UNAVAILABLE
            reason = f"consecutive_misses_{new_miss_count}_and_grace_{int(elapsed_seconds)}s_met"
        else:
            new_availability = PostingAvailability.NOT_SEEN
            reason = f"consecutive_misses_{new_miss_count}_awaiting_grace_or_threshold"

    else:
        # Already UNAVAILABLE
        new_miss_count = current.miss_count + 1
        new_missing_since = current.missing_since or inventory_end
        new_availability = PostingAvailability.UNAVAILABLE
        reason = f"already_unavailable_consecutive_misses_{new_miss_count}"

    new_state = current.model_copy(
        update={
            "availability": new_availability,
            "missing_since": new_missing_since,
            "miss_count": new_miss_count,
            "policy_fingerprint": policy_fingerprint,
        }
    )

    decision = AvailabilityDecision(
        source_key=current.source_key,
        canonical_job_id=current.canonical_job_id,
        scope_id=current.scope_id,
        manifest_id=manifest_id,
        run_id=run_id,
        from_availability=current.availability,
        to_availability=new_availability,
        reason=reason,
        miss_count=new_miss_count,
        missing_since=new_missing_since,
        event_time=inventory_end,
        policy_fingerprint=policy_fingerprint,
    )
    return (new_state, decision)

