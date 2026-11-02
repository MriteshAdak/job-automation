"""Data records and contracts for pipeline orchestration and recovery (RUN-01).

Formalizes:
- RunRequest / RunAttempt execution lifecycle records
- StageWorkRecord / StageReceipt granular work tracking
- PostingBinding linking canonical identity, revision, material hash, and C06 snapshot
- AssessmentSelection tracking authoritative selection generation and purpose
- QuarantineRecord for persisted normalization issues
- RunReport companion summary detailing stage outcomes and count metrics
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    PipelineStage,
    RunStatus,
)
from job_automation.contracts.errors import ClassifiedError, ValidationIssue
from job_automation.contracts.postings import NormalizedPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey, UtcDatetime
from job_automation.contracts.runs import RunSummary


class AssessmentMode(str, enum.Enum):
    """Pipeline assessment execution mode."""

    RULES = "rules"
    LLM = "llm"


class OwnerKind(str, enum.Enum):
    """Owner process kind acquiring the deployment worker lock."""

    SEARCH = "search"
    GENERATION = "generation"
    MAINTENANCE = "maintenance"


class WorkItemState(str, enum.Enum):
    """Lifecycle state of an individual stage work item."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunRequest(ContractModel):
    """Frozen input specification for a logical pipeline run."""

    run_id: uuid.UUID = Field(description="Unique pipeline execution UUID")
    assessment_mode: AssessmentMode = Field(
        default=AssessmentMode.RULES,
        description="Assessment mode: rules (deterministic) or llm",
    )
    source_keys: list[str] | None = Field(
        default=None,
        description="Explicit selected source keys (None = active sources from config)",
    )
    primary_strategy: ContextStrategy = Field(
        default=ContextStrategy.JSON,
        description="Primary context strategy for LLM assessment: json or rag",
    )
    app_config_hash: str = Field(description="SHA-256 fingerprint of application configuration")
    policy_fingerprint: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of active search policy",
    )
    profile_snapshot_hash: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of approved candidate profile snapshot",
    )
    availability_policy_hash: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of availability policy",
    )
    sync_mapping_hash: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of Salesforce sync mapping config",
    )
    run_settings_hash: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of run settings",
    )
    trigger_kind: str | None = Field(
        default=None,
        description="Trigger kind: manual, scheduled, retry",
    )
    schedule_occurrence_id: str | None = Field(
        default=None,
        description="Schedule occurrence UUID if scheduled",
    )
    slot_key: str | None = Field(
        default=None,
        description="Intended slot key if scheduled",
    )
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp of this run request",
    )


class RunAttempt(ContractModel):
    """Record of a single execution attempt of a logical pipeline run."""

    attempt_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique attempt UUID",
    )
    run_id: uuid.UUID = Field(description="Logical run UUID")
    attempt_sequence: int = Field(
        ge=1,
        description="Monotonically increasing attempt sequence (1 for initial, 2+ for resumes)",
    )
    status: str = Field(
        default="running",
        description="Attempt status: running, succeeded, failed, partial, interrupted",
    )
    started_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Start timestamp of this attempt",
    )
    completed_at: UtcDatetime | None = Field(
        default=None,
        description="Completion timestamp of this attempt",
    )
    exit_code: int | None = Field(
        default=None,
        description="Process exit code",
    )
    error: ClassifiedError | None = Field(
        default=None,
        description="Safe error detail if attempt failed",
    )


class StageWorkRecord(ContractModel):
    """Granular work item tracking record for stage-level idempotency and recovery."""

    work_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique work item UUID",
    )
    run_id: uuid.UUID = Field(description="Logical run UUID")
    attempt_id: uuid.UUID = Field(description="Attempt UUID owning this execution")
    stage_name: str = Field(description="Pipeline stage name")
    work_key: str = Field(description="Domain-specific work key, e.g. source:arbeitnow or job:<uuid>")
    input_fingerprint: str = Field(description="SHA-256 composite fingerprint of all inputs")
    output_id: str | None = Field(
        default=None,
        description="Identifier of produced output (e.g. revision_id, assessment_id, plan_id)",
    )
    state: WorkItemState = Field(
        default=WorkItemState.PENDING,
        description="Current state of this work item",
    )
    checkpoint_data: dict[str, Any] | None = Field(
        default=None,
        description="Resumable checkpoint data for interrupted items",
    )
    error: ClassifiedError | None = Field(
        default=None,
        description="Safe error if work item failed",
    )
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )
    updated_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp",
    )


class PostingBinding(ContractModel):
    """Immutable binding between canonical job, revision, material hash, and full C06 snapshot."""

    binding_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique binding UUID",
    )
    canonical_job_id: uuid.UUID = Field(description="Stable canonical job UUID")
    revision_id: uuid.UUID = Field(description="Posting revision UUID")
    normalized_content_hash: str = Field(description="SHA-256 material content hash of normalized posting")
    raw_reference: str = Field(description="Storage reference of raw payload file")
    raw_content_hash: str = Field(description="SHA-256 content hash of raw payload bytes")
    source_key: SourceKey = Field(description="Source provider/board/posting key")
    c06_snapshot: NormalizedPosting = Field(description="Complete C06 NormalizedPosting snapshot")
    mapper_version: str = Field(default="1.0", description="Source mapping version")
    normalizer_version: str = Field(default="1.0", description="Normalizer version")
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )


class AssessmentSelection(ContractModel):
    """Authoritative assessment selection manifest for a canonical job."""

    selection_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique selection UUID",
    )
    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    candidate_id: uuid.UUID = Field(description="Candidate UUID")
    purpose: str = Field(default="assessment", description="Assessment purpose")
    input_fingerprint: str = Field(description="SHA-256 composite input fingerprint")
    assessment_id: uuid.UUID = Field(description="Authoritative selected C11 Assessment UUID")
    evaluated_at: UtcDatetime = Field(description="Timestamp when assessment was performed")
    generation_token: str = Field(description="Monotonically advancing selection generation token")
    is_selected_final: bool = Field(default=True, description="Whether this is the authoritative selected final")
    disposition: AssessmentDisposition = Field(description="Selected assessment disposition")
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )


class QuarantineRecord(ContractModel):
    """Durable quarantine record for normalization or ingestion failures."""

    quarantine_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique quarantine record UUID",
    )
    run_id: uuid.UUID = Field(description="Logical run UUID")
    source_key: SourceKey = Field(description="Source key of failed posting")
    raw_reference: str = Field(description="Storage reference to raw payload file")
    record_index: int | None = Field(default=None, description="Record index within raw batch")
    issues: list[ValidationIssue] = Field(description="List of validation issues causing quarantine")
    draft: SourceJobDraft | None = Field(default=None, description="Partial draft if available")
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )


class RunReport(ContractModel):
    """Detailed companion execution report complementing C15 RunSummary."""

    report_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique report UUID",
    )
    run_id: uuid.UUID = Field(description="Logical run UUID")
    attempt_id: uuid.UUID = Field(description="Attempt UUID")
    report_version: str = Field(default="1.0", description="Report format version")
    summary: RunSummary = Field(description="Canonical C15 RunSummary")
    stage_outcomes: dict[str, str] = Field(
        default_factory=dict,
        description="Status outcome per pipeline stage (e.g. fetch: succeeded)",
    )
    source_details: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Detailed metrics and outcome per attempted source",
    )
    reused_work: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of reused work items per stage (e.g. assess: 5)",
    )
    quarantine_count: int = Field(default=0, description="Total quarantined postings")
    pending_work_ids: list[str] = Field(
        default_factory=list,
        description="Referenced IDs of pending work items",
    )
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Report creation timestamp",
    )

