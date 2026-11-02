"""Canonical multi-source availability aggregation (IDENTITY-02-S06).

Rules over current effective source memberships:
1. Any source active -> canonical active.
2. Otherwise any source not_seen -> canonical not_seen.
3. Otherwise any source unknown, unresolved membership evidence, or no sources -> canonical unknown.
4. Only when all participating sources are unavailable -> canonical unavailable.

Guarantees:
- Candidate application progress, notes, and decisions are completely untouched.
- An unavailable source never closes a canonical vacancy if another linked source is active.
"""

from __future__ import annotations

from typing import Sequence

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import UtcDatetime
from job_automation.identity.availability.models import SourcePostingAvailability


def aggregate_canonical_availability(
    source_states: Sequence[SourcePostingAvailability],
) -> tuple[PostingAvailability, str]:
    """Aggregate per-source availability states into canonical availability.

    Returns:
        tuple[PostingAvailability, str]: (canonical_availability, explanation_reason)
    """
    if not source_states:
        return (PostingAvailability.UNKNOWN, "no_linked_sources")

    # 1. Any source active -> canonical active
    active_sources = [s for s in source_states if s.availability == PostingAvailability.ACTIVE]
    if active_sources:
        return (
            PostingAvailability.ACTIVE,
            f"linked_source_active ({len(active_sources)}/{len(source_states)} active)",
        )

    # 2. Otherwise any source not_seen -> canonical not_seen
    not_seen_sources = [s for s in source_states if s.availability == PostingAvailability.NOT_SEEN]
    if not_seen_sources:
        return (
            PostingAvailability.NOT_SEEN,
            f"linked_source_not_seen ({len(not_seen_sources)}/{len(source_states)} not_seen)",
        )

    # 3. Otherwise any source unknown -> canonical unknown
    unknown_sources = [s for s in source_states if s.availability == PostingAvailability.UNKNOWN]
    if unknown_sources:
        return (
            PostingAvailability.UNKNOWN,
            f"linked_source_unknown ({len(unknown_sources)}/{len(source_states)} unknown)",
        )

    # 4. Only when all participating sources are unavailable -> canonical unavailable
    return (
        PostingAvailability.UNAVAILABLE,
        f"all_linked_sources_unavailable ({len(source_states)}/{len(source_states)} unavailable)",
    )


def aggregate_observation_timestamps(
    source_states: Sequence[SourcePostingAvailability],
    fallback_first_seen: UtcDatetime,
    fallback_last_seen: UtcDatetime,
) -> tuple[UtcDatetime, UtcDatetime]:
    """Derive earliest and most recent observation timestamps across effective sources."""
    if not source_states:
        return (fallback_first_seen, fallback_last_seen)

    earliest = min(s.first_seen_at for s in source_states)
    latest = max(s.last_seen_at for s in source_states)
    return (min(earliest, fallback_first_seen), max(latest, fallback_last_seen))

