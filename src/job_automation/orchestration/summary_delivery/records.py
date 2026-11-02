"""Contracts and data models for AUTO-03 per-run summary delivery.

Defines:
- DeliveryState & NotificationState: Bounded lifecycle states
- RunCompletionReceipt: Durable receipt captured at RUN-01 completion boundary
- RunSummaryProjection: Versioned compact projection mapped to the SF-09 summary target
- SummaryDelivery: Outbox delivery entity tracking retry budgets, deadlines, and remote state
- DeliveryAttemptRecord: Granular audit record for each HTTP attempt and outcome
- TargetAcknowledgment: Remote acknowledgment evidence
- DeliveryReport: Inspectable summary report for CLI and runner output
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.runs import RunSummary


class DeliveryState(StrEnum):
    """Lifecycle state of a local SummaryDelivery outbox record."""

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    RETRY_WAIT = "retry_wait"
    RECONCILE_REQUIRED = "reconcile_required"
    DELIVERED = "delivered"
    BLOCKED = "blocked"
    EXHAUSTED = "exhausted"


class NotificationState(StrEnum):
    """Observed state of remote Salesforce completion notification execution."""

    NONE = "none"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RunCompletionReceipt(ContractModel):
    """Durable receipt produced at the RUN-01 completion boundary.

    Freezes the pipeline run result, counting units, source coverage, and attempt
    context into an immutable record before delivery dispatch.
    """

    receipt_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique receipt identifier",
    )
    run_id: uuid.UUID = Field(
        description="Stable logical pipeline execution UUID",
    )
    attempt_sequence: int = Field(
        ge=1,
        default=1,
        description="Pipeline run attempt sequence number",
    )
    revision: int = Field(
        ge=1,
        default=1,
        description="Monotonically increasing completion revision for resumes",
    )
    start_time: UtcDatetime = Field(
        description="Pipeline run start timestamp in UTC",
    )
    completed_at: UtcDatetime = Field(
        description="Pipeline run completion or interruption timestamp in UTC",
    )
    status: str = Field(
        description="Pipeline terminal status: success, partial, or failed",
    )
    c15_summary: RunSummary = Field(
        description="Authoritative C15 RunSummary record",
    )
    assessment_mode: str = Field(
        default="rules",
        description="Assessment evaluation mode (rules or llm)",
    )
    sources_attempted: list[str] = Field(
        default_factory=list,
        description="All source keys attempted during discovery",
    )
    sources_succeeded: list[str] = Field(
        default_factory=list,
        description="Source keys that completed discovery successfully",
    )
    sources_failed: list[str] = Field(
        default_factory=list,
        description="Source keys that failed or were incomplete",
    )
    quarantined_records_count: int = Field(
        ge=0,
        default=0,
        description="Count of invalid/quarantined raw records",
    )
    availability_transitions_count: int = Field(
        ge=0,
        default=0,
        description="Count of canonical job availability transitions",
    )
    reused_assessments_count: int = Field(
        ge=0,
        default=0,
        description="Count of cached/reused assessments (zero-model calls)",
    )
    model_invocations_count: int = Field(
        ge=0,
        default=0,
        description="Count of physical model inference calls dispatched",
    )
    exit_code: int = Field(
        default=0,
        description="Pipeline runner process exit code",
    )
    receipt_hash: str = Field(
        default="",
        description="SHA-256 canonical hash of the completion receipt payload",
    )
    is_final: bool = Field(
        default=True,
        description="Whether this represents a finalized terminal result",
    )
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Receipt creation timestamp in UTC",
    )

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of this receipt."""
        canonical_dict = {
            "run_id": str(self.run_id),
            "attempt_sequence": self.attempt_sequence,
            "revision": self.revision,
            "start_time": self.start_time.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "status": self.status,
            "c15_summary": json.loads(self.c15_summary.model_dump_json()),
            "sources_attempted": sorted(self.sources_attempted),
            "sources_succeeded": sorted(self.sources_succeeded),
            "sources_failed": sorted(self.sources_failed),
            "quarantined_records_count": self.quarantined_records_count,
            "exit_code": self.exit_code,
        }
        raw_bytes = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()

    @model_validator(mode="after")
    def _ensure_hash(self) -> RunCompletionReceipt:
        if not self.receipt_hash:
            object.__setattr__(self, "receipt_hash", self.compute_hash())
        return self


class RunSummaryProjection(ContractModel):
    """Compact, sanitized summary projection targeted for the SF-09 remote record.

    Adheres strictly to the remote allowlist: no secrets, no absolute filesystem
    paths, no raw candidate profiles, and no unbounded stack traces.
    """

    mapping_version: str = Field(
        default="1.0",
        description="Target projection contract version",
    )
    org_id: str = Field(
        description="Verified Salesforce Organization ID",
    )
    run_id: uuid.UUID = Field(
        description="Stable logical run UUID",
    )
    completion_key: str = Field(
        description="Stable composite completion key (org_id:run_id)",
    )
    revision: int = Field(
        ge=1,
        default=1,
        description="Monotonically increasing summary revision",
    )
    start_time: UtcDatetime = Field(
        description="Run start timestamp in UTC",
    )
    end_time: UtcDatetime = Field(
        description="Run completion timestamp in UTC",
    )
    duration_seconds: float = Field(
        ge=0.0,
        description="Observed run duration in seconds",
    )
    pipeline_status: str = Field(
        description="Pipeline outcome: success, partial, or failed",
    )
    headline: str = Field(
        max_length=255,
        description="Concise, truthful headline summarizing outcome and observation units",
    )
    summary_text: str = Field(
        max_length=2000,
        description="Sanitized summary description adhering to documented C15 units",
    )
    source_postings_count: int = Field(
        ge=0,
        default=0,
        description="Raw source postings observed across all sources",
    )
    canonical_jobs_new: int = Field(
        ge=0,
        default=0,
        description="Count of newly discovered canonical jobs registered",
    )
    canonical_jobs_updated: int = Field(
        ge=0,
        default=0,
        description="Count of canonical jobs receiving material updates",
    )
    canonical_jobs_duplicate: int = Field(
        ge=0,
        default=0,
        description="Count of duplicate raw observations",
    )
    eligible_count: int = Field(
        ge=0,
        default=0,
        description="Count of canonical jobs newly evaluated as eligible",
    )
    review_count: int = Field(
        ge=0,
        default=0,
        description="Count of canonical jobs flagged for review",
    )
    rejected_count: int = Field(
        ge=0,
        default=0,
        description="Count of canonical jobs classified as rejected",
    )
    sync_succeeded: int = Field(
        ge=0,
        default=0,
        description="Count of successful C12 sync operations",
    )
    sync_failed: int = Field(
        ge=0,
        default=0,
        description="Count of failed C12 sync operations",
    )
    quarantined_count: int = Field(
        ge=0,
        default=0,
        description="Count of quarantined raw records",
    )
    sources_attempted: list[str] = Field(
        default_factory=list,
        description="Sources attempted in this run",
    )
    sources_succeeded: list[str] = Field(
        default_factory=list,
        description="Sources that succeeded in this run",
    )
    sources_failed: list[str] = Field(
        default_factory=list,
        description="Sources that failed or were incomplete",
    )
    error_summary: str | None = Field(
        default=None,
        max_length=500,
        description="Allowlisted, sanitized error digest without confidential paths or secrets",
    )
    pending_work_summary: str | None = Field(
        default=None,
        max_length=500,
        description="Concise summary of pending/retry work",
    )
    first_result_snapshot_hash: str = Field(
        description="Immutable SHA-256 hash of the initial completion projection",
    )
    current_revision_hash: str = Field(
        description="SHA-256 hash of this specific projection revision",
    )
    is_first_completion: bool = Field(
        default=True,
        description="True if this is the first terminal completion for this run UUID",
    )
    truncated: bool = Field(
        default=False,
        description="True if any textual field was deterministically truncated to fit limits",
    )

    def compute_revision_hash(self) -> str:
        """Compute deterministic SHA-256 hash of this projection revision."""
        d = {
            "mapping_version": self.mapping_version,
            "org_id": self.org_id,
            "run_id": str(self.run_id),
            "completion_key": self.completion_key,
            "revision": self.revision,
            "pipeline_status": self.pipeline_status,
            "headline": self.headline,
            "source_postings_count": self.source_postings_count,
            "canonical_jobs_new": self.canonical_jobs_new,
            "canonical_jobs_updated": self.canonical_jobs_updated,
            "canonical_jobs_duplicate": self.canonical_jobs_duplicate,
            "eligible_count": self.eligible_count,
            "review_count": self.review_count,
            "rejected_count": self.rejected_count,
            "sync_succeeded": self.sync_succeeded,
            "sync_failed": self.sync_failed,
            "quarantined_count": self.quarantined_count,
            "error_summary": self.error_summary,
        }
        raw = json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class SummaryDelivery(ContractModel):
    """Durable outbox entity representing the summary delivery lane for a run.

    Enforces:
    - Exactly one delivery lane per (org_id, run_id).
    - Monotonically increasing revisions with immutable payload hashes.
    - Durable attempt counters and retry deadlines that survive process restarts.
    - Explicit decoupling between summary-record delivery and Flow notification execution.
    """

    delivery_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique delivery outbox record UUID",
    )
    run_id: uuid.UUID = Field(
        description="Stable logical run UUID",
    )
    org_id: str = Field(
        description="Target Salesforce Organization ID",
    )
    completion_key: str = Field(
        description="Composite completion key (org_id:run_id)",
    )
    revision: int = Field(
        ge=1,
        default=1,
        description="Current summary revision number",
    )
    state: DeliveryState = Field(
        default=DeliveryState.PENDING,
        description="Delivery lifecycle state",
    )
    target_object: str = Field(
        default="Run_Summary__c",
        description="Target Salesforce sObject API name",
    )
    target_external_id_field: str = Field(
        default="Run_Id__c",
        description="Target external ID field name",
    )
    payload_json: str = Field(
        description="Serialized JSON representation of current RunSummaryProjection",
    )
    payload_hash: str = Field(
        description="SHA-256 hash of the current revision payload",
    )
    first_completion_hash: str = Field(
        description="Immutable SHA-256 hash of the initial completion payload",
    )
    dispatch_attempts: int = Field(
        ge=0,
        default=0,
        description="Lifetime dispatch/send attempts executed",
    )
    reconcile_attempts: int = Field(
        ge=0,
        default=0,
        description="Lifetime reconciliation/query attempts executed",
    )
    retry_window_start: UtcDatetime = Field(
        description="Timestamp when retry window opened",
    )
    retry_deadline: UtcDatetime = Field(
        description="Hard deadline after which automatic retries cease",
    )
    next_due_at: UtcDatetime | None = Field(
        default=None,
        description="Next eligible dispatch timestamp after backoff/jitter",
    )
    remote_record_id: str | None = Field(
        default=None,
        description="Remote Salesforce Record ID once created or acknowledged",
    )
    acknowledged_revision: int | None = Field(
        default=None,
        description="Revision successfully acknowledged by Salesforce",
    )
    acknowledged_hash: str | None = Field(
        default=None,
        description="Payload hash confirmed by remote acknowledgment",
    )
    notification_state: NotificationState = Field(
        default=NotificationState.NONE,
        description="Observed state of remote completion notification execution",
    )
    notification_receipt_id: str | None = Field(
        default=None,
        description="Remote notification receipt identifier if observed",
    )
    last_error_category: str | None = Field(
        default=None,
        description="Category of the most recent failure",
    )
    last_error_code: str | None = Field(
        default=None,
        description="Safe error code from most recent failure",
    )
    last_error_message: str | None = Field(
        default=None,
        description="Safe error message summary from most recent failure",
    )
    claim_token: str | None = Field(
        default=None,
        description="Worker lock claim token during in_flight dispatch",
    )
    claimed_at: UtcDatetime | None = Field(
        default=None,
        description="Timestamp when work was claimed by worker",
    )
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Record creation timestamp in UTC",
    )
    updated_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp in UTC",
    )
    acknowledged_at: UtcDatetime | None = Field(
        default=None,
        description="Timestamp when delivery was acknowledged in UTC",
    )


class DeliveryAttemptRecord(ContractModel):
    """Detailed audit record for a single delivery dispatch or reconciliation attempt."""

    attempt_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique attempt record UUID",
    )
    delivery_id: uuid.UUID = Field(
        description="Parent delivery outbox UUID",
    )
    run_id: uuid.UUID = Field(
        description="Associated pipeline run UUID",
    )
    attempt_sequence: int = Field(
        ge=1,
        description="Attempt sequence number",
    )
    operation_kind: str = Field(
        description="Operation performed: upsert or query_reconcile",
    )
    status: str = Field(
        description="Attempt result: succeeded, failed, or ambiguous",
    )
    http_status: int | None = Field(
        default=None,
        description="HTTP status code received if applicable",
    )
    duration_ms: float = Field(
        ge=0.0,
        default=0.0,
        description="Duration of attempt in milliseconds",
    )
    remote_outcome: str | None = Field(
        default=None,
        description="Observed remote outcome (e.g. acknowledged, not_sent, rejected, unknown)",
    )
    recovery_action: str | None = Field(
        default=None,
        description="Classified recovery action (e.g. retry_later, reconcile, fix_configuration)",
    )
    safe_error_code: str | None = Field(
        default=None,
        description="Allowlisted provider error code",
    )
    safe_error_message: str | None = Field(
        default=None,
        description="Sanitized error description without secret leakage",
    )
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Attempt execution timestamp in UTC",
    )


class TargetAcknowledgment(ContractModel):
    """Confirmed acknowledgment from the summary target adapter."""

    is_present: bool = Field(
        default=True,
        description="Whether the summary record exists remotely (True) or is authoritatively absent (False)",
    )
    org_id: str = Field(
        description="Verified Salesforce Organization ID",
    )
    record_id: str = Field(
        default="",
        description="Salesforce Record ID (15 or 18 chars)",
    )
    run_id: uuid.UUID = Field(
        description="Run UUID of the acknowledged summary",
    )
    applied_revision: int = Field(
        ge=0,
        default=0,
        description="Summary revision applied on the remote record",
    )
    applied_hash: str = Field(
        default="",
        description="Payload hash applied on the remote record",
    )
    completion_key: str = Field(
        description="Completion entitlement key",
    )
    is_created: bool = Field(
        default=False,
        description="True if newly created, False if updated",
    )
    notification_state: NotificationState = Field(
        default=NotificationState.PENDING,
        description="Observed notification execution state",
    )
    notification_receipt_id: str | None = Field(
        default=None,
        description="Remote Flow receipt identifier if available",
    )
    acknowledged_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Acknowledgment timestamp in UTC",
    )


class DeliveryReport(ContractModel):
    """Human-readable and structured inspection report for a summary delivery."""

    run_id: uuid.UUID = Field(
        description="Pipeline run UUID",
    )
    delivery_state: DeliveryState = Field(
        description="Current local delivery state",
    )
    notification_state: NotificationState = Field(
        default=NotificationState.NONE,
        description="Observed remote notification state",
    )
    dispatch_attempts: int = Field(
        default=0,
        description="Total dispatch attempts executed",
    )
    reconcile_attempts: int = Field(
        default=0,
        description="Total reconciliation queries executed",
    )
    remote_record_id: str | None = Field(
        default=None,
        description="Remote Salesforce Record ID",
    )
    next_due_at: UtcDatetime | None = Field(
        default=None,
        description="Next scheduled retry timestamp if in retry_wait",
    )
    last_error: str | None = Field(
        default=None,
        description="Last safe error message if delivery is not delivered",
    )
    acknowledged_at: UtcDatetime | None = Field(
        default=None,
        description="Delivery acknowledgment timestamp",
    )
