"""Domain models and result records for availability tracking (IDENTITY-02-S01).

Guarantees:
- Strict separation between machine-owned availability and candidate application progress.
- Explicit tracking of per-scope source posting states and decisions.
- Append-only decision audit trail.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey, UtcDatetime


class SourcePostingAvailability(ContractModel):
    """Machine-owned availability state of a specific source posting in a given inventory scope."""

    source_key: SourceKey = Field(description="Originating source posting key")
    scope_id: str = Field(min_length=1, description="Inventory scope identifier")
    canonical_job_id: uuid.UUID | None = Field(
        default=None,
        description="Associated canonical job UUID if mapped",
    )
    availability: PostingAvailability = Field(
        default=PostingAvailability.UNKNOWN,
        description="Current availability status of this source posting in this scope",
    )
    first_seen_at: UtcDatetime = Field(description="Earliest observation timestamp")
    last_seen_at: UtcDatetime = Field(description="Most recent observation timestamp")
    missing_since: UtcDatetime | None = Field(
        default=None,
        description="Timestamp of first qualifying miss in the current miss streak",
    )
    miss_count: int = Field(
        default=0,
        ge=0,
        description="Consecutive qualifying complete inventory misses in current streak",
    )
    policy_fingerprint: str | None = Field(
        default=None,
        description="Fingerprint of effective policy active during the last decision",
    )


class AvailabilityDecision(ContractModel):
    """Durable audit record of an availability transition or evaluation."""

    decision_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique identifier of this availability decision",
    )
    source_key: SourceKey = Field(description="Affected source posting key")
    canonical_job_id: uuid.UUID | None = Field(
        default=None,
        description="Affected canonical job UUID if mapped",
    )
    scope_id: str = Field(min_length=1, description="Inventory scope evaluated")
    manifest_id: str | None = Field(
        default=None,
        description="Manifest identifier supplying evidence",
    )
    run_id: uuid.UUID | None = Field(
        default=None,
        description="Execution run UUID",
    )
    from_availability: PostingAvailability = Field(
        description="Availability status prior to evaluation",
    )
    to_availability: PostingAvailability = Field(
        description="Availability status after evaluation",
    )
    reason: str = Field(min_length=1, description="Explanation or rule code for transition")
    miss_count: int = Field(ge=0, description="Streak count at time of decision")
    missing_since: UtcDatetime | None = Field(
        default=None,
        description="Anchor timestamp of current miss streak",
    )
    event_time: UtcDatetime = Field(description="Timestamp of evidence causing decision")
    policy_fingerprint: str | None = Field(
        default=None,
        description="Policy fingerprint applied",
    )


class SourceChangeResult(ContractModel):
    """Result summary of a source posting availability transition."""

    source_key: SourceKey = Field(description="Source posting key")
    scope_id: str = Field(description="Scope evaluated")
    canonical_job_id: uuid.UUID | None = Field(default=None, description="Canonical job UUID if mapped")
    previous_availability: PostingAvailability = Field(description="State before change")
    new_availability: PostingAvailability = Field(description="State after change")
    reason: str = Field(description="Transition reason code")
    miss_count: int = Field(ge=0, description="Current miss count")
    missing_since: UtcDatetime | None = Field(default=None, description="Miss anchor timestamp")
    transition_time: UtcDatetime = Field(description="Effective transition timestamp")


class CanonicalChangeResult(ContractModel):
    """Result summary of an aggregate canonical job availability update."""

    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    previous_availability: PostingAvailability = Field(description="Canonical state before change")
    new_availability: PostingAvailability = Field(description="Canonical state after change")
    reason: str = Field(description="Aggregation reason code")
    participating_sources_count: int = Field(ge=0, description="Count of linked source postings")
    active_sources_count: int = Field(ge=0, description="Count of currently active source postings")
    transition_time: UtcDatetime = Field(description="Effective transition timestamp")


class AvailabilityProcessResult(ContractModel):
    """Summary of processing an inventory fetch manifest for availability."""

    run_id: uuid.UUID = Field(description="Pipeline run UUID")
    source_key: str = Field(description="Source identifier")
    scope_id: str = Field(description="Scope identifier")
    manifest_id: str = Field(description="Manifest identifier")
    is_complete_inventory: bool = Field(description="Whether the manifest represents complete traversal")
    eligible_for_negative_inference: bool = Field(
        description="Whether negative evidence was permitted from this manifest",
    )
    blocked_reason: str | None = Field(
        default=None,
        description="Reason why negative evidence was blocked, if applicable",
    )
    positive_observations_count: int = Field(
        default=0,
        ge=0,
        description="Number of positive sightings processed",
    )
    miss_evaluations_count: int = Field(
        default=0,
        ge=0,
        description="Number of baseline postings evaluated for absence",
    )
    source_changes: list[SourceChangeResult] = Field(
        default_factory=list,
        description="Source posting availability transitions",
    )
    canonical_changes: list[CanonicalChangeResult] = Field(
        default_factory=list,
        description="Canonical job availability transitions",
    )
    is_replay: bool = Field(
        default=False,
        description="Whether this manifest was an idempotent replay of an already processed inventory",
    )

