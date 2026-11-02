"""Contract records, data models, and enums for operations (OPS-01).

Formalizes:
- OperationsSettings for backup destination, retention rules, capacity limits
- RetentionInventory for comprehensive storage and reference tracking
- CapacityReport for local disk and remote quota monitoring
- CleanupPlan and CleanupResult for reviewable, safe retention enforcement
- RemoteRecoveryExport for candidate-owned Salesforce recovery
- BackupManifest for complete, verifiable recovery sets
- RestorePlan and RestoreResult for isolated recovery and path relocation
- MaintenanceReport for auditability and operator guidance
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime


class OperationStatus(str, enum.Enum):
    """Execution status for maintenance operations."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class CapacityStatus(str, enum.Enum):
    """Storage capacity assessment status."""

    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RemoteCompleteness(str, enum.Enum):
    """Completeness state of remote recovery export."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"
    LOCAL_ONLY_ABSENT_SF04 = "local_only_absent_sf04"


class ItemClass(str, enum.Enum):
    """Classification of managed data storage items."""

    RAW_PAYLOAD = "raw_payload"
    PROFILE_EVIDENCE = "profile_evidence"
    ARTIFACT = "artifact"
    CONTEXT_INDEX = "context_index"
    DATABASE = "database"
    LOG = "log"
    CONFIG = "config"
    METADATA = "metadata"
    UNKNOWN = "unknown"


class ProtectionReason(str, enum.Enum):
    """Reason why an item is protected from deletion."""

    REFERENCED_BY_RECORD = "referenced_by_record"
    UNFINISHED_WORK = "unfinished_work"
    PROFILE_FACT = "profile_fact"
    ACTIVE_INDEX = "active_index"
    PINNED_INDEX = "pinned_index"
    RETENTION_DISABLED = "retention_disabled"
    WITHIN_RETENTION_PERIOD = "within_retention_period"
    SOURCE_POLICY_PROTECTED = "source_policy_protected"
    UNKNOWN_SCHEMA_OR_FORMAT = "unknown_schema_or_format"
    QUARANTINE_PROTECTED = "quarantine_protected"


class BackupSettings(ContractModel):
    """Configuration for local backup creation and lifecycle."""

    destination: str | None = Field(
        default=None,
        description="Path to backup destination folder (e.g. external volume or dedicated backup root)",
    )
    keep_generations: int = Field(
        default=3,
        ge=1,
        description="Minimum number of successful backup generations to preserve",
    )
    max_age_days: int = Field(
        default=30,
        ge=1,
        description="Eligibility cutoff in days for pruning old backups",
    )
    pinned_backups: list[str] = Field(
        default_factory=list,
        description="List of backup IDs to keep indefinitely",
    )
    require_remote_export: bool = Field(
        default=False,
        description="If True, backup fails if remote Salesforce export is missing or incomplete",
    )
    remote_export_freshness_hours: float = Field(
        default=24.0,
        ge=0.1,
        description="Maximum allowed age of Salesforce candidate export in hours",
    )


class RetentionSettings(ContractModel):
    """Configuration for bulky raw data and log retention."""

    enabled: bool = Field(
        default=False,
        description="Master switch for cleanup apply; deletion is disabled unless explicitly True",
    )
    raw_payloads_days: int = Field(
        default=90,
        ge=1,
        description="Age cutoff in days for unreferenced raw payloads",
    )
    logs_days: int = Field(
        default=30,
        ge=1,
        description="Age cutoff in days for closed log files",
    )
    staging_days: int = Field(
        default=7,
        ge=1,
        description="Age cutoff in days for abandoned staging files",
    )
    backups_days: int = Field(
        default=30,
        ge=1,
        description="Age cutoff in days for pruning completed backups",
    )
    source_overrides: dict[str, int] = Field(
        default_factory=dict,
        description="Per-source raw retention cutoff overrides in days",
    )


class CapacitySettings(ContractModel):
    """Storage capacity thresholds and reserve margins."""

    reserve_bytes: int = Field(
        default=1073741824,
        ge=0,
        description="Absolute reserve in bytes (default 1 GiB)",
    )
    reserve_percent: float = Field(
        default=10.0,
        ge=0.0,
        le=100.0,
        description="Relative reserve percentage of volume capacity (default 10%)",
    )
    warning_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        description="Multiplier of reserve at which capacity warnings are raised",
    )


class OperationLimits(ContractModel):
    """Execution budgets and timeouts for operations."""

    timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        description="Timeout for operations lock acquisition and file processing",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        description="Batch size for item processing and queries",
    )


class OperationsSettings(ContractModel):
    """Consolidated configuration for all operations."""

    backup: BackupSettings = Field(default_factory=BackupSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    capacity: CapacitySettings = Field(default_factory=CapacitySettings)
    limits: OperationLimits = Field(default_factory=OperationLimits)


class InventoryItem(ContractModel):
    """A managed data item tracked in the retention inventory."""

    item_id: str = Field(description="Unique identifier for the item (e.g. relative path or record ID)")
    root_relative_path: str = Field(description="Normalized path relative to deployment data root")
    item_class: ItemClass = Field(description="Classification of this item")
    size_bytes: int = Field(ge=0, description="Size in bytes")
    content_hash: str = Field(description="SHA-256 content hash")
    observed_at: UtcDatetime = Field(description="Observation or last modified timestamp in UTC")
    is_referenced: bool = Field(default=True, description="True if referenced by active or historical database records")
    referencing_records: list[str] = Field(
        default_factory=list,
        description="List of record references (e.g. 'raw_postings:arbeitnow/default/123')",
    )
    is_protected: bool = Field(default=True, description="True if protected from deletion")
    protection_reasons: list[ProtectionReason] = Field(
        default_factory=list,
        description="Reasons justifying protection",
    )
    source_policy_restriction: str | None = Field(
        default=None,
        description="Specific source or legal restriction",
    )


class RetentionInventory(ContractModel):
    """Complete inventory of all stored items and references across the deployment."""

    inventory_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    data_root: str = Field(description="Deployment data root directory")
    scanned_at: UtcDatetime = Field(description="Timestamp when inventory scan completed")
    store_fingerprint: str = Field(description="Deterministic hash of schema and table counts")
    total_files_count: int = Field(ge=0)
    total_files_bytes: int = Field(ge=0)
    items: list[InventoryItem] = Field(default_factory=list)
    table_counts: dict[str, int] = Field(default_factory=dict)
    unknown_files: list[str] = Field(default_factory=list)
    protection_summary: dict[str, int] = Field(default_factory=dict)


class CapacityVolumeReport(ContractModel):
    """Capacity measurement for a specific filesystem volume."""

    volume_path: str = Field(description="Path on volume inspected")
    device_id: str = Field(description="Identifier for physical or logical volume")
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)
    required_bytes: int = Field(ge=0, description="Estimated bytes required for intended operation")
    reserve_bytes: int = Field(ge=0, description="Enforced reserve threshold")
    status: CapacityStatus = Field(description="Assessment status (ok, warning, blocked, unknown)")
    is_same_disk: bool = Field(
        default=False,
        description="True if sharing physical disk with source data root",
    )


class RemoteCapacityObservation(ContractModel):
    """Measured remote Salesforce storage and API capacity."""

    source: str = Field(default="SF-04")
    status: str = Field(default="unknown")
    measured_at: UtcDatetime | None = None
    api_limit: int | None = None
    api_used: int | None = None
    data_limit_mb: float | None = None
    data_used_mb: float | None = None
    file_limit_mb: float | None = None
    file_used_mb: float | None = None
    notes: str = Field(default="Remote capacity unknown: SF-04 handoff absent")


class CapacityReport(ContractModel):
    """Consolidated storage capacity report across volumes and remote services."""

    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    measured_at: UtcDatetime
    overall_status: CapacityStatus
    source_volume: CapacityVolumeReport
    destination_volume: CapacityVolumeReport | None = None
    staging_volume: CapacityVolumeReport | None = None
    remote_capacity: RemoteCapacityObservation = Field(default_factory=RemoteCapacityObservation)
    issues: list[ClassifiedError] = Field(default_factory=list)


class CleanupCandidate(ContractModel):
    """A specific item selected for deletion in a cleanup plan."""

    candidate_id: str = Field(description="Item identifier")
    root_relative_path: str = Field(description="Path relative to deployment data root")
    item_class: ItemClass
    size_bytes: int = Field(ge=0)
    expected_hash: str
    age_days: float = Field(ge=0.0)
    cutoff_time: UtcDatetime
    reason: str


class CleanupPlan(ContractModel):
    """Reviewable, immutable plan for deleting eligible expired unreferenced files."""

    plan_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created_at: UtcDatetime
    expires_at: UtcDatetime
    store_fingerprint: str
    policy_fingerprint: str
    plan_hash: str
    cutoff_time: UtcDatetime
    candidates: list[CleanupCandidate] = Field(default_factory=list)
    protected_items_count: int = Field(ge=0)
    blocked_items_count: int = Field(ge=0)
    protected_by_class: dict[str, int] = Field(default_factory=dict)
    estimated_reclaim_bytes: int = Field(ge=0)
    status: str = Field(default="planned")


class CleanupJournalEntry(ContractModel):
    """Journal entry recording progress through cleanup stages."""

    journal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    plan_id: uuid.UUID
    step_number: int = Field(ge=1)
    item_path: str
    stage: str
    status: str
    reclaimed_bytes: int = Field(default=0, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class CleanupResult(ContractModel):
    """Outcome of applying a verified cleanup plan."""

    plan_id: uuid.UUID
    plan_hash: str
    applied_at: UtcDatetime
    status: OperationStatus
    attempted_count: int = Field(ge=0)
    deleted_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    actual_reclaimed_bytes: int = Field(ge=0)
    issues: list[ClassifiedError] = Field(default_factory=list)
    quarantine_dir: str | None = None


class RemoteRecoveryExport(ContractModel):
    """Candidate-owned Salesforce export package for disaster recovery."""

    scan_id: str = Field(description="Stable identifier for the export scan")
    start_time: UtcDatetime
    end_time: UtcDatetime
    org_id: str
    object_coverage: list[str] = Field(default_factory=list)
    expected_count: int = Field(default=0, ge=0)
    read_count: int = Field(default=0, ge=0)
    saved_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    missing_fields: list[str] = Field(default_factory=list)
    per_record_tokens: dict[str, str] = Field(default_factory=dict)
    completeness_status: RemoteCompleteness = Field(
        default=RemoteCompleteness.LOCAL_ONLY_ABSENT_SF04
    )
    checksum: str = Field(default="")
    notes: str = Field(default="")


class BackupFileEntry(ContractModel):
    """Inventory entry for a file included in a backup set."""

    root_relative_path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    item_class: ItemClass


class BackupManifest(ContractModel):
    """Manifest describing a consistent backup set."""

    backup_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created_at: UtcDatetime
    format_version: str = Field(default="1.0")
    app_version: str
    schema_version: int = Field(ge=1)
    migration_checksums: dict[int, str] = Field(default_factory=dict)
    local_cut_time: UtcDatetime
    remote_capture_interval: tuple[UtcDatetime, UtcDatetime] | None = None
    source_data_root: str
    files: list[BackupFileEntry] = Field(default_factory=list)
    total_files_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    mapping_versions: dict[str, str] = Field(default_factory=dict)
    omissions: list[str] = Field(default_factory=list)
    completeness_status: str = Field(description="'complete_local', 'complete_local_and_remote', 'partial'")
    remote_export: RemoteRecoveryExport | None = None
    failure_domain_evidence: dict[str, Any] = Field(default_factory=dict)
    verification_results: dict[str, Any] = Field(default_factory=dict)


class RestorePlan(ContractModel):
    """Preflight plan for restoring a backup into an isolated data root."""

    plan_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    backup_id: uuid.UUID
    backup_path: str
    source_data_root: str
    target_data_root: str
    created_at: UtcDatetime
    files_to_restore: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    path_mappings_count: int = Field(default=0, ge=0)
    capacity_status: CapacityStatus = Field(default=CapacityStatus.OK)
    conflicts: list[str] = Field(default_factory=list)
    is_valid: bool = Field(default=True)


class RestoreResult(ContractModel):
    """Outcome of restoring and verifying a backup set."""

    plan_id: uuid.UUID
    backup_id: uuid.UUID
    target_data_root: str
    restored_at: UtcDatetime
    status: OperationStatus
    restored_files_count: int = Field(ge=0)
    relocated_paths_count: int = Field(ge=0)
    integrity_check_passed: bool
    foreign_key_check_passed: bool
    issues: list[ClassifiedError] = Field(default_factory=list)
    activation_checklist: list[str] = Field(default_factory=list)


class MaintenanceReport(ContractModel):
    """Diagnostic and audit report emitted after any maintenance command."""

    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    operation_type: str = Field(
        description="e.g. 'capacity', 'cleanup_preview', 'cleanup_apply', 'backup_create', 'backup_verify', 'restore_plan', 'restore_apply'"
    )
    started_at: UtcDatetime
    completed_at: UtcDatetime
    status: OperationStatus
    counts: dict[str, int] = Field(default_factory=dict)
    bytes_processed: int = Field(default=0, ge=0)
    classified_errors: list[ClassifiedError] = Field(default_factory=list)
    pending_work: list[str] = Field(default_factory=list)
    safe_next_action: str = Field(default="")
    artifact_references: list[str] = Field(default_factory=list)
    integrity_verified: bool = Field(default=False)
    restore_tested: bool = Field(default=False)
    remote_coverage_status: str = Field(default="local_only")

