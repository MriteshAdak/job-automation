"""C12 SyncOperation contracts.

Manages persistent Salesforce sync operations. Enforces that only locally owned
machine fields enter the sync payload, preserving candidate-owned status, notes,
and follow-ups in Salesforce.
"""

from __future__ import annotations

import uuid

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    AssessmentDisposition,
    PostingAvailability,
    SyncOperationState,
)
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime


class SyncPayload(ContractModel):
    """Machine-owned fields synchronized to Salesforce.

    Strictly excludes candidate-owned fields (e.g. application progress,
    candidate notes, follow-up dates, manual overrides).
    """

    canonical_job_id: uuid.UUID = Field(description="Target canonical job UUID")
    job_title: str = Field(min_length=1, description="Latest normalized job title")
    company_name: str = Field(min_length=1, description="Resolved employer name")
    availability: PostingAvailability = Field(description="Posting availability")
    assessment_disposition: AssessmentDisposition = Field(
        description="Machine assessment disposition"
    )
    relevance_score: float | None = Field(
        default=None, ge=0.0, description="Machine relevance score"
    )
    score_scale: str | None = Field(default=None, description="Score scale")
    assessment_reasons: str = Field(description="Summary explanation of assessment")
    source_urls: list[str] = Field(
        default_factory=list, description="Observed source posting URLs"
    )
    last_evaluated_at: UtcDatetime = Field(
        description="Timestamp of the evaluated assessment"
    )


class SyncOperation(ContractModel):
    """C12 Salesforce Sync Operation.

    Represents a queued or executed write operation to Salesforce.
    Sequenced and fingerprinted to prevent stale writes.
    """

    operation_id: uuid.UUID = Field(description="Unique operation UUID")
    canonical_job_id: uuid.UUID = Field(description="Associated canonical job UUID")
    payload_version: str = Field(
        min_length=1, description="Sequential or timestamped version token of this update"
    )
    payload_fingerprint: str = Field(
        min_length=1, description="Content hash of the locally owned payload"
    )
    locally_owned_payload: SyncPayload = Field(
        description="Strictly machine-owned fields to push to Salesforce"
    )
    attempt_count: int = Field(ge=0, default=0, description="Number of delivery attempts made")
    max_attempts: int = Field(gt=0, default=3, description="Maximum retry attempts permitted")
    state: SyncOperationState = Field(
        default=SyncOperationState.PENDING,
        description="Current outbox operation state",
    )
    remote_record_id: str | None = Field(
        default=None,
        description="Salesforce Job__c record ID once created or acknowledged",
    )
    remote_acknowledged_at: UtcDatetime | None = Field(
        default=None,
        description="Timestamp when Salesforce acknowledged the upsert",
    )
    error: ClassifiedError | None = Field(
        default=None,
        description="Error details from the most recent failed attempt",
    )

