"""Identity domain models for matching outcomes, review cases, and merge operations."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.interfaces import IdentityMatchDecision
from job_automation.contracts.primitives import SourceKey, UtcDatetime


class MatchOutcome(str, Enum):
    """Specific identity resolution outcome categories."""

    NEW_CANONICAL = "new_canonical_job"
    EXACT_SOURCE_SAME_CONTENT = "exact_source_same_content"
    EXACT_SOURCE_NEW_REVISION = "exact_source_new_revision"
    STRONG_KEY_MATCH = "strong_key_match"
    REVIEW_CANDIDATE = "review_candidate"
    CONFLICT_HELD = "conflict_held"


class CompanyIdentity(ContractModel):
    """Resolved company entity with stable UUID."""

    company_id: uuid.UUID = Field(description="Stable canonical UUID for employer entity")
    canonical_name: str = Field(min_length=1, description="Canonical employer display name")
    normalized_name: str = Field(min_length=1, description="Normalized name for conservative lookup")
    created_at: UtcDatetime = Field(description="When the company was first registered")
    updated_at: UtcDatetime = Field(description="When the company record was last updated")


class ReviewCase(ContractModel):
    """Durable identity review case for human inspection."""

    case_id: str = Field(description="Unique review case identifier")
    status: str = Field(
        default="pending", description="Status: pending, accepted, rejected, deferred"
    )
    reason: str = Field(min_length=1, description="Reason for proposing review")
    candidate_job_ids: list[uuid.UUID] = Field(
        default_factory=list, description="IDs of existing candidate canonical jobs"
    )
    source_key: SourceKey = Field(description="Source key of the incoming posting")
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Structured matching evidence and similarity metrics"
    )
    decision_actor: str | None = Field(
        default=None, description="Human reviewer or system agent making the decision"
    )
    decision_reason: str | None = Field(
        default=None, description="Rationale provided for the decision"
    )
    decided_at: UtcDatetime | None = Field(
        default=None, description="Timestamp when decision was recorded"
    )
    created_at: UtcDatetime = Field(description="When this case was created")
    updated_at: UtcDatetime = Field(description="When this case was last updated")


class MergeOperation(ContractModel):
    """Append-only audit record for a canonical job merge."""

    operation_id: str = Field(description="Unique operation UUID for this merge")
    operation_type: str = Field(default="merge", description="Operation type: merge")
    surviving_canonical_id: uuid.UUID = Field(
        description="Surviving canonical job UUID after merge"
    )
    merged_canonical_id: uuid.UUID = Field(
        description="Predecessor canonical job UUID merged into survivor"
    )
    actor: str = Field(min_length=1, description="Actor who executed the merge")
    reason: str = Field(min_length=1, description="Reason/evidence for the merge")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Full snapshots of predecessor states, source keys, and revision IDs",
    )
    created_at: UtcDatetime = Field(description="When the merge was performed")
    reversed_by_operation_id: str | None = Field(
        default=None, description="Operation ID that reversed this merge if applicable"
    )
    reversed_at: UtcDatetime | None = Field(
        default=None, description="Timestamp when this merge was reversed"
    )


class ReversalOperation(ContractModel):
    """Record of a successful merge reversal restoring separate identities."""

    operation_id: str = Field(description="Unique operation UUID for this reversal")
    target_merge_operation_id: str = Field(
        description="Operation ID of the merge being reversed"
    )
    surviving_canonical_id: uuid.UUID = Field(
        description="Canonical job UUID that was the survivor"
    )
    restored_canonical_id: uuid.UUID = Field(
        description="Canonical job UUID restored to independent status"
    )
    actor: str = Field(min_length=1, description="Actor who reversed the merge")
    reason: str = Field(min_length=1, description="Reason for reversing the merge")
    reversed_at: UtcDatetime = Field(description="When the reversal was performed")


class IdentityResolutionResult(ContractModel):
    """Complete result of resolving a normalized posting into canonical identity."""

    canonical_job_id: uuid.UUID = Field(description="Assigned canonical job UUID")
    revision: PostingRevision = Field(description="Active or created posting revision")
    decision: IdentityMatchDecision = Field(description="Protocol match decision record")
    outcome: MatchOutcome = Field(description="Specific resolution outcome category")
    is_new_canonical: bool = Field(description="True if a new canonical job was created")
    is_new_revision: bool = Field(description="True if a new revision snapshot was created")
    review_case_id: str | None = Field(
        default=None, description="ID of review case if flagged as review candidate"
    )
    observation_id: uuid.UUID = Field(description="UUID of the recorded posting observation")

