"""Contracts and records for Salesforce org capacity, metadata portability, and candidate data export (SF-04).

Enforces:
- Structured capacity observations and operation-specific decisions (publication, files, export).
- Strict separation between canonical identifiers and transient Salesforce IDs.
- UTF-8 JSON/JSONL export data model preserving exact candidate values, nulls, and German characters.
- Relationship closure between Job records and parent Company records.
- Independent export verification manifests and reports.
"""

from __future__ import annotations

import uuid
from typing import Any
from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.primitives import UtcDatetime


class CapacityResource(ContractModel):
    """Capacity metrics for a single measured Salesforce resource."""

    name: str = Field(description="Resource identifier, e.g. daily_api_requests, data_storage_mb")
    unit: str = Field(description="Unit of measurement (e.g. requests, MB, count)")
    max_value: float | None = Field(default=None, description="Maximum allocation (None if unknown)")
    remaining_value: float | None = Field(default=None, description="Remaining available allowance")
    used_value: float | None = Field(default=None, description="Computed used quantity (max - remaining)")
    percent_used: float | None = Field(default=None, description="Percentage of allowance consumed (0-100)")
    status: str = Field(default="unknown", description="Resource evaluation status: ok, warning, blocked, unknown")
    reason: str | None = Field(default=None, description="Explanatory detail for non-ok status")


class CapacityObservation(ContractModel):
    """Point-in-time observation of Salesforce org limits and capacity."""

    org_id: str = Field(description="Bound source Salesforce organization ID")
    api_version: str = Field(description="Configured REST API version used for query")
    measured_at: UtcDatetime = Field(description="UTC timestamp of the measurement")
    evidence_source: str = Field(default="rest_limits", description="Evidence origin (e.g. rest_limits, setup_storage)")
    resources: dict[str, CapacityResource] = Field(
        default_factory=dict, description="Resource observations keyed by resource name"
    )
    overall_status: str = Field(default="unknown", description="Overall org status: ok, warning, blocked, unknown")
    notes: str = Field(default="", description="Operator diagnostic notes or error context")


class CapacityDecision(ContractModel):
    """Operation-specific decision derived from capacity observation."""

    operation_kind: str = Field(description="Target operation: publication, file_upload, export_read")
    status: str = Field(description="Decision status: ok, warning, blocked, unknown")
    allowed: bool = Field(default=False, description="Whether the operation is permitted to proceed")
    reason: str = Field(default="", description="Detailed rationale for the decision")
    recheck_after_seconds: int = Field(default=300, description="Recommended delay before rechecking")
    estimated_cost: dict[str, Any] = Field(default_factory=dict, description="Estimated resource costs evaluated")


class ExportFileEntry(ContractModel):
    """Entry describing a single data file within a portable export package."""

    relative_path: str = Field(description="Relative path within the export package")
    size_bytes: int = Field(ge=0, description="Exact file size in bytes")
    sha256: str = Field(description="SHA-256 hex digest of file contents")
    record_count: int = Field(ge=0, description="Number of logical records in the file")


class CompanyExportRow(ContractModel):
    """Portable export record for a parent Company__c entity."""

    canonical_company_id: uuid.UUID = Field(description="Canonical company UUID (External ID)")
    salesforce_id: str = Field(description="Remote Salesforce record ID")
    name: str = Field(description="Standard Name field value")
    company_name: str | None = Field(default=None, description="Extended company business name")
    system_modstamp: str = Field(description="Remote SystemModstamp token")
    observed_at: UtcDatetime = Field(description="UTC timestamp when record was observed")


class JobExportRow(ContractModel):
    """Portable export record for an evaluated Job__c entity with candidate fields."""

    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID (External ID)")
    salesforce_id: str = Field(description="Remote Salesforce record ID")
    canonical_company_id: uuid.UUID | None = Field(
        default=None, description="Canonical company UUID if company relationship exists"
    )
    company_salesforce_id: str | None = Field(
        default=None, description="Original remote Company__c lookup ID (provenance only)"
    )
    name: str = Field(description="Standard Name (Job Title) field value")
    job_title: str | None = Field(default=None, description="Extended job title")
    application_progress: str | None = Field(
        default=None, description="Candidate-owned Application_Progress__c (exact value or None)"
    )
    candidate_notes: str | None = Field(
        default=None, description="Candidate-owned Candidate_Notes__c (exact multiline text or None)"
    )
    candidate_decision: str | None = Field(
        default=None, description="Candidate-owned Candidate_Decision__c (exact value or None)"
    )
    follow_up_date: str | None = Field(
        default=None, description="Candidate-owned Follow_Up_Date__c in YYYY-MM-DD format or None"
    )
    interview_date: str | None = Field(
        default=None, description="Candidate-owned Interview_Date__c in ISO-8601 format or None"
    )
    availability: str | None = Field(default=None, description="Observed Availability__c status")
    assessment_disposition: str | None = Field(default=None, description="Machine Assessment_Disposition__c")
    system_modstamp: str = Field(description="Remote SystemModstamp token")
    observed_at: UtcDatetime = Field(description="UTC timestamp when record was observed")


class CandidateSnapshotExportRow(ContractModel):
    """Export record for historical candidate snapshots captured in local storage."""

    snapshot_id: uuid.UUID = Field(description="Local candidate snapshot UUID")
    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    remote_record_id: str = Field(description="Salesforce record ID at time of snapshot")
    mapping_version: str = Field(description="Mapping configuration version active during snapshot")
    snapshot_hash: str = Field(description="SHA-256 hash of extracted candidate fields")
    candidate_fields: dict[str, Any] = Field(description="Exact candidate fields dictionary")
    source_modification_token: str = Field(description="SystemModstamp token captured with snapshot")
    observed_at: UtcDatetime = Field(description="UTC timestamp when snapshot was taken")


class FieldHistoryExportRow(ContractModel):
    """Export record for an observed Salesforce Field History tracking entry."""

    history_id: str = Field(description="Salesforce History record ID")
    canonical_job_id: uuid.UUID | None = Field(
        default=None, description="Resolved canonical job UUID if known"
    )
    salesforce_parent_id: str = Field(description="Salesforce Job__c parent record ID")
    field_name: str = Field(description="Tracked field name")
    created_at: UtcDatetime = Field(description="History event timestamp")
    created_by_id: str = Field(description="Actor User ID reference (provenance only)")
    old_value: Any | None = Field(default=None, description="Previous value or None")
    new_value: Any | None = Field(default=None, description="New value or None")


class ExportIssueRow(ContractModel):
    """Issue or gap encountered during remote data export."""

    issue_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Issue UUID")
    canonical_id: str | None = Field(default=None, description="Canonical ID involved if applicable")
    salesforce_id: str | None = Field(default=None, description="Salesforce ID involved if applicable")
    issue_type: str = Field(description="Issue category: invalid_uuid, missing_parent, missing_field, duplicate_id")
    details: dict[str, Any] = Field(default_factory=dict, description="Structured diagnostics")


class ExportManifest(ContractModel):
    """Manifest describing a completed candidate-owned data export package."""

    format_version: str = Field(default="1.0", description="Export format specification version")
    export_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique export identifier")
    scan_id: str = Field(description="Scan identifier binding multiple pages/steps")
    org_id: str = Field(description="Source Salesforce organization ID")
    api_version: str = Field(description="REST API version used for export")
    mapping_version: str = Field(description="SyncMappingConfig version")
    mapping_hash: str = Field(description="SHA-256 hash of sync mapping config")
    metadata_digest: str = Field(default="", description="Digest of verified project metadata")
    start_time: UtcDatetime = Field(description="UTC timestamp when export scan started")
    end_time: UtcDatetime = Field(description="UTC timestamp when export completed")
    capture_scope: str = Field(default="project_candidate_data", description="Declared scope of export")
    expected_counts: dict[str, int] = Field(default_factory=dict, description="Expected counts per entity")
    read_counts: dict[str, int] = Field(default_factory=dict, description="Records read per entity")
    saved_counts: dict[str, int] = Field(default_factory=dict, description="Records successfully saved per entity")
    skipped_counts: dict[str, int] = Field(default_factory=dict, description="Records skipped per entity")
    error_counts: dict[str, int] = Field(default_factory=dict, description="Errors encountered per entity")
    missing_fields: list[str] = Field(default_factory=list, description="Required candidate fields missing from org")
    pagination_completed: bool = Field(default=True, description="True if all pages were traversed without truncation")
    completeness_status: str = Field(
        default="complete", description="Completeness status: complete, partial, incomplete, local_only_absent_sf04"
    )
    omissions: list[str] = Field(default_factory=list, description="Explicit omissions or exclusions")
    files: list[ExportFileEntry] = Field(default_factory=list, description="Files contained in package")
    source_tokens: dict[str, str] = Field(
        default_factory=dict, description="Per-job SystemModstamp tokens for conflict detection"
    )
    notes: str = Field(default="", description="Operator notes and diagnostic summary")


class ExportVerificationReport(ContractModel):
    """Report generated by independent offline verification of an export package."""

    is_valid: bool = Field(description="Whether the export package passes all integrity and closure checks")
    completeness_status: str = Field(description="Evaluated completeness: complete, partial, incomplete, invalid")
    checked_files: list[str] = Field(default_factory=list, description="List of relative file paths verified")
    total_records: dict[str, int] = Field(default_factory=dict, description="Record counts verified per file")
    issues: list[str] = Field(default_factory=list, description="Integrity or relationship violations")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings or gaps")

