"""GEN-01 typed data records, companion envelopes, and lifecycle structures."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime


class ObservationIssueCategory(StrEnum):
    """Categorized issues for generation requests observed during polling."""

    UNMAPPED_JOB = "unmapped_job"
    INVALID_OPTIONS = "invalid_options"
    CONFLICTING_IDENTITY = "conflicting_identity"
    PERMISSION_DENIED = "permission_denied"
    MALFORMED_ROW = "malformed_row"
    JOB_UNAVAILABLE = "job_unavailable"


class RemoteRequestState(StrEnum):
    """Recognized remote Salesforce Generation_Request__c states."""

    PENDING = "Pending"
    RUNNING = "Running"
    UPLOAD_PENDING = "Upload_Pending"
    READY_FOR_REVIEW = "Ready_for_Review"
    FAILED = "Failed"
    UNKNOWN = "Unknown"


class GenerationRequestObservation(ContractModel):
    """Durable observation of an outbound Salesforce generation request."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    observation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    org_id: str = Field(min_length=15, max_length=18)
    salesforce_request_id: str = Field(min_length=15, max_length=18)
    canonical_salesforce_id: str = Field(min_length=18, max_length=18)
    client_request_key: str | None = None
    local_request_id: uuid.UUID | None = None
    canonical_job_id: uuid.UUID | None = None
    remote_state: str = Field(default="Pending")
    observed_options_digest: str | None = None
    observed_at: UtcDatetime
    remote_updated_at: UtcDatetime | None = None
    issue_category: ObservationIssueCategory | None = None
    issue_message: str | None = None
    raw_record: dict[str, Any] = Field(default_factory=dict)


class FreezeManifest(ContractModel):
    """Immutable input snapshot manifest prepared by GEN-02."""

    manifest_id: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    canonical_job_id: uuid.UUID
    posting_revision_id: str = Field(min_length=1)
    posting_revision_hash: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    context_strategy: ContextStrategy = Field(default=ContextStrategy.JSON)
    target_language: str = Field(default="de")
    options_digest: str = Field(min_length=1)
    availability_status: str = Field(default="active")
    allow_unavailable_job: bool = Field(default=False)
    frozen_at: UtcDatetime
    snapshot_refs: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class GenerationStage(StrEnum):
    """Logical stages coordinated by GEN-01."""

    FREEZE = "freeze"
    CONTEXT = "context"
    DRAFT = "draft"
    VALIDATION = "validation"
    RENDERING = "rendering"
    DELIVERY = "delivery"


class StageStatus(StrEnum):
    """Status of an individual stage checkpoint."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class StageCheckpoint(ContractModel):
    """Durable checkpoint receipt for a single generation stage."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    checkpoint_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    stage_name: str
    stage_operation_id: str
    checkpoint_revision: int = 1
    status: StageStatus = StageStatus.PENDING
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    output_ref: str | None = None
    output_hash: str | None = None
    error: ClassifiedError | None = None
    checkpoint_data: dict[str, Any] = Field(default_factory=dict)


class StageAttempt(ContractModel):
    """Audit record for a physical execution attempt of a stage."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    attempt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    stage_name: str
    stage_operation_id: str
    attempt_sequence: int = 1
    worker_attempt_id: uuid.UUID
    status: StageStatus = StageStatus.IN_PROGRESS
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    error: ClassifiedError | None = None


class ProjectionStatus(StrEnum):
    """Status of a remote state projection intent."""

    PENDING = "pending"
    SENDING = "sending"
    UNCERTAIN = "uncertain"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"


class ProjectionIntent(ContractModel):
    """Durable intent to project local state to Salesforce Generation_Request__c."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    intent_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    projection_revision: int = 1
    operation_marker: str
    desired_remote_state: str
    expected_remote_state: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ProjectionStatus = ProjectionStatus.PENDING
    attempts: int = 0
    created_at: UtcDatetime
    updated_at: UtcDatetime
    acknowledged_at: UtcDatetime | None = None
    uncertain_at: UtcDatetime | None = None
    last_error: ClassifiedError | None = None


class ArtifactDeliveryRecord(ContractModel):
    """Delivery receipt for a specific rendered format (e.g. docx or pdf)."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    delivery_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    artifact_format: str = Field(description="docx or pdf")
    artifact_id: uuid.UUID
    artifact_hash: str
    remote_file_id: str | None = None
    delivery_status: str = Field(default="local_only")
    delivered_at: UtcDatetime | None = None
    receipt_data: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(ContractModel):
    """Report from GEN-04 draft validation."""

    is_valid: bool = True
    fatal_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated_draft_hash: str | None = None
    report_ref: str | None = None


class GenerationWorkerReport(ContractModel):
    """Report summarizing the outcome of a worker polling and processing cycle."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    worker_attempt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    started_at: UtcDatetime
    completed_at: UtcDatetime
    scanned_requests: int = 0
    admitted_requests: int = 0
    reused_requests: int = 0
    completed_requests: int = 0
    blocked_requests: int = 0
    failed_requests: int = 0
    recovery_actions: list[str] = Field(default_factory=list)
    pending_reasons: dict[str, str] = Field(default_factory=dict)
    errors: list[ClassifiedError] = Field(default_factory=list)
    exit_code: int = 0
