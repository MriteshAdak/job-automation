"""SYNC-01 companion records, enums, and lifecycle contracts.

Defines:
- Publication purpose, decision, and entity type enums
- SyncSubmission linking C11 Assessment to publication lifecycle
- SyncPlan and SyncWriteStep models for ordered, fingerprinted delivery
- RemoteEntityMapping and CandidateFieldSnapshot for ownership preservation
- Operational results (SyncPlanResult, DrainResult, ReconciliationResult, CandidateBackupResult)
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.sync import SyncOperation


class PublicationPurpose(StrEnum):
    """Caller publication intent for an assessment."""

    PRIMARY_FINAL = "primary_final"
    INTERMEDIATE = "intermediate"
    COMPARISON = "comparison"


class PublicationDecision(StrEnum):
    """Decision reached regarding publication to Salesforce."""

    PUBLISH_INITIAL = "publish_initial"
    UPDATE_TRACKED = "update_tracked"
    LOCAL_ONLY_REJECTED = "local_only_rejected"
    LOCAL_ONLY_COMPARISON = "local_only_comparison"
    NO_CHANGE = "no_change"


class EntityType(StrEnum):
    """Entity lane types for ordered delivery."""

    COMPANY = "company"
    JOB = "job"


class SyncStepState(StrEnum):
    """Lifecycle state of a discrete sync write step."""

    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyncSubmission(ContractModel):
    """Submission envelope around C11 Assessment for publication planning."""

    submission_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique submission identifier"
    )
    assessment: Assessment = Field(
        description="Complete C11 Assessment record (rules or LLM)"
    )
    canonical_job_id: uuid.UUID = Field(
        description="Associated canonical job UUID"
    )
    posting_revision: str = Field(
        min_length=1, description="Posting revision identifier or content hash"
    )
    evaluated_at: UtcDatetime = Field(
        description="Stable evaluation timestamp of the assessment"
    )
    generation_token: str = Field(
        min_length=1, description="Active input-generation token"
    )
    run_id: str | None = Field(
        default=None, description="Pipeline run ID if available"
    )
    publication_purpose: PublicationPurpose = Field(
        default=PublicationPurpose.PRIMARY_FINAL,
        description="Purpose of submission; non-primary results are not published",
    )
    job_title: str = Field(
        min_length=1, default="Job Vacancy", description="Normalized job title"
    )
    company_name: str = Field(
        min_length=1, description="Canonical company name"
    )
    canonical_company_id: uuid.UUID | None = Field(
        default=None, description="Stable canonical company UUID"
    )
    source_urls: list[str] = Field(
        default_factory=list, description="Associated source URLs"
    )
    availability: PostingAvailability = Field(
        default=PostingAvailability.ACTIVE,
        description="Current observed availability of the job",
    )

    @model_validator(mode="after")
    def _validate_assessment_consistency(self) -> SyncSubmission:
        if self.assessment.canonical_job_id != self.canonical_job_id:
            raise ValueError(
                f"Assessment canonical_job_id '{self.assessment.canonical_job_id}' "
                f"does not match submission canonical_job_id '{self.canonical_job_id}'"
            )
        if self.assessment.posting_revision != self.posting_revision:
            raise ValueError(
                f"Assessment posting_revision '{self.assessment.posting_revision}' "
                f"does not match submission posting_revision '{self.posting_revision}'"
            )
        return self


class SyncWriteStep(ContractModel):
    """Discrete ordered mutation step (Company or Job) within a SyncPlan."""

    step_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique write step UUID"
    )
    plan_id: uuid.UUID = Field(description="Parent SyncPlan UUID")
    operation_id: uuid.UUID | None = Field(
        default=None, description="C12 SyncOperation UUID if this is a job step"
    )
    entity_type: EntityType = Field(description="Target entity type: company or job")
    entity_id: uuid.UUID = Field(
        description="Target canonical entity UUID (company_id or job_id)"
    )
    sequence_number: int = Field(
        ge=1, description="Per-entity monotonic sequence number"
    )
    target_object: str = Field(
        min_length=1, description="Salesforce sObject name (e.g. Job__c, Company__c)"
    )
    external_id_field: str = Field(
        min_length=1, description="Salesforce External ID field API name"
    )
    external_id_value: str = Field(
        min_length=1, description="External ID value to upsert"
    )
    relationship_field: str | None = Field(
        default=None,
        description="Lookup field name on this object linking to parent entity",
    )
    depends_on_step_id: uuid.UUID | None = Field(
        default=None,
        description="Prior step ID that must succeed before this step executes",
    )
    frozen_payload: dict[str, Any] = Field(
        description="Frozen mapped fields to send to Salesforce (strictly machine-owned)"
    )
    step_fingerprint: str = Field(
        min_length=1, description="Content hash of this write step"
    )
    state: SyncStepState = Field(
        default=SyncStepState.PENDING, description="Current step execution state"
    )
    may_have_been_sent: bool = Field(
        default=False,
        description="True if request may have reached Salesforce (pre-send intent set)",
    )
    attempt_count: int = Field(
        ge=0, default=0, description="Number of attempts made on this step"
    )
    next_attempt_at: UtcDatetime | None = Field(
        default=None, description="Timestamp after which next attempt is permitted"
    )
    reconciliation_marker: str = Field(
        min_length=1, description="Unique marker written into remote payload for reconciliation"
    )
    remote_record_id: str | None = Field(
        default=None, description="Salesforce record ID once confirmed"
    )
    acknowledged_at: UtcDatetime | None = Field(
        default=None, description="Timestamp of confirmed remote acknowledgment"
    )
    error: ClassifiedError | None = Field(
        default=None, description="Classified error from most recent failure"
    )


class SyncPlan(ContractModel):
    """Atomic publication plan containing ordered write steps."""

    plan_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique plan UUID"
    )
    canonical_job_id: uuid.UUID = Field(
        description="Target canonical job UUID"
    )
    assessment_id: uuid.UUID = Field(
        description="Evaluated C11 Assessment UUID"
    )
    mapping_version: str = Field(
        min_length=1, description="Version of the mapping configuration used"
    )
    mapping_hash: str = Field(
        min_length=1, description="SHA-256 hash of mapping configuration used"
    )
    plan_fingerprint: str = Field(
        min_length=1, description="Full logical projection fingerprint"
    )
    selection_token: str = Field(
        min_length=1, description="Input-generation token driving this plan"
    )
    run_id: str | None = Field(
        default=None, description="Associated pipeline run ID"
    )
    publication_decision: PublicationDecision = Field(
        description="Publication decision reached"
    )
    created_at: UtcDatetime = Field(
        description="Timestamp when plan was generated and persisted"
    )
    steps: list[SyncWriteStep] = Field(
        default_factory=list, description="Ordered write steps in this plan"
    )


class RemoteEntityMapping(ContractModel):
    """Confirmed mapping between local canonical entity and remote Salesforce record."""

    org_id: str = Field(min_length=1, description="Salesforce organization ID")
    object_name: str = Field(min_length=1, description="Salesforce sObject API name")
    entity_id: uuid.UUID = Field(description="Canonical entity UUID")
    external_id: str = Field(min_length=1, description="External ID value")
    salesforce_id: str = Field(min_length=1, description="Remote Salesforce record 18-char ID")
    confirmed_sequence: int = Field(ge=1, description="Highest confirmed sequence number")
    reconciliation_marker: str | None = Field(
        default=None, description="Last confirmed reconciliation marker"
    )
    acknowledged_at: UtcDatetime = Field(
        description="Timestamp of latest remote acknowledgment"
    )


class CandidateFieldSnapshot(ContractModel):
    """Locally persisted snapshot of candidate-owned fields read from Salesforce."""

    snapshot_id: uuid.UUID = Field(
        default_factory=uuid.uuid4, description="Unique snapshot UUID"
    )
    org_id: str = Field(min_length=1, description="Salesforce organization ID")
    canonical_job_id: uuid.UUID = Field(description="Target canonical job UUID")
    remote_record_id: str = Field(
        min_length=1, description="Salesforce Job__c record ID"
    )
    mapping_version: str = Field(
        min_length=1, description="Mapping version used during observation"
    )
    snapshot_hash: str = Field(
        min_length=1, description="Hash of candidate field values"
    )
    candidate_fields: dict[str, Any] = Field(
        description="Observed candidate-owned fields (status, notes, decisions, follow-ups)"
    )
    source_modification_token: str | None = Field(
        default=None, description="Remote system modstamp or etag if available"
    )
    observed_at: UtcDatetime = Field(
        description="Timestamp when fields were observed from Salesforce"
    )
    created_at: UtcDatetime = Field(
        description="Timestamp when snapshot was persisted locally"
    )


class SyncPlanResult(ContractModel):
    """Outcome of planning an assessment submission."""

    plan: SyncPlan
    sync_operation: SyncOperation | None = None
    is_published: bool
    publication_decision: PublicationDecision


class DrainResult(ContractModel):
    """Summary of a bounded outbox drain pass."""

    operations_claimed: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    steps_reconciled: int = 0
    remaining_due: int = 0
    errors: list[ClassifiedError] = Field(default_factory=list)


class ReconciliationResult(ContractModel):
    """Summary of a bounded reconciliation pass."""

    steps_checked: int = 0
    steps_confirmed: int = 0
    steps_superseded: int = 0
    barriers_retained: int = 0
    errors: list[ClassifiedError] = Field(default_factory=list)


class CandidateBackupResult(ContractModel):
    """Summary of a candidate field backup scan."""

    records_read: int = 0
    snapshots_saved: int = 0
    is_complete: bool = True
    errors: list[ClassifiedError] = Field(default_factory=list)
