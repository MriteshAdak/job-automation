"""Data records and contracts for native Windows startup and scheduling (AUTO-01).

Formalizes:
- ScheduleDefinition: versioned deployment scheduling configuration.
- ScheduleOccurrence: durable (deployment, schedule, version, slot) record.
- LaunchAttemptRecord: diagnostic audit trail of execution attempts.
- IdentityResourceManifest: non-secret identity and environment manifest.
- ReadinessProbeResult: model supervisor readiness status.
- SchedulingSettings: configuration file root.
- DispatchReport: execution report returned by the dispatcher.
"""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import Field, field_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.primitives import UtcDatetime


class ScheduleKind(str, enum.Enum):
    """Supported work kinds for scheduling."""

    SEARCH = "search"
    GENERATION = "generation"


class OccurrenceOutcome(str, enum.Enum):
    """Lifecycle outcome of a schedule occurrence."""

    DUE = "due"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED_BUSY = "skipped_busy"
    EXPIRED = "expired"
    COALESCED = "coalesced"


class BootstrapCategory(str, enum.Enum):
    """Classification of pre-launch bootstrap and readiness health."""

    OK = "ok"
    MISSING_CONFIG = "missing_config"
    ACCESS_DENIED = "access_denied"
    RUNTIME_OFFLINE = "runtime_offline"
    MODEL_MISSING = "model_missing"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    TIMEOUT = "timeout"


class ScheduleDefinition(ContractModel):
    """Versioned schedule definition for a deployment."""

    deployment_id: str = Field(description="Unique deployment identifier")
    schedule_id: str = Field(default="daily_search", description="Identifier for this schedule")
    version: int = Field(default=1, ge=1, description="Monotonically increasing definition version")
    definition_hash: str = Field(default="", description="SHA-256 fingerprint of definition fields")
    enabled: bool = Field(default=False, description="Whether this schedule is active for execution")
    work_kind: ScheduleKind = Field(default=ScheduleKind.SEARCH, description="Target work kind")
    timezone: str = Field(default="Europe/Berlin", description="IANA timezone for scheduling intent")
    target_times: list[str] = Field(
        default_factory=lambda: ["07:00"],
        description="Local wall-clock target times in HH:MM format",
    )
    cadence_minutes: int | None = Field(
        default=None,
        description="Optional repeating interval in minutes (e.g. 5 for frequent polling)",
    )
    activation_epoch: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Earliest UTC instant for admitting occurrences (no historical backfill)",
    )
    max_lateness_hours: int = Field(
        default=24,
        ge=1,
        description="Maximum lateness window in hours before missed slots expire",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts per occurrence",
    )
    retry_delay_seconds: int = Field(
        default=60,
        ge=1,
        description="Initial delay between retry attempts",
    )
    app_config_path: str = Field(default="", description="Absolute path to application configuration")
    data_root: str = Field(default="", description="Absolute path to deployment data root")
    run_config_path: str | None = Field(default=None, description="Absolute path to run configuration")
    assessment_mode: str = Field(default="rules", description="Assessment mode: rules or llm")
    llm_strategy: str = Field(default="json", description="LLM strategy: json or rag")
    command_timeout_seconds: int = Field(default=3600, ge=30, description="Process execution timeout")
    created_at: UtcDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: UtcDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of invariant definition fields."""
        payload = {
            "deployment_id": self.deployment_id,
            "schedule_id": self.schedule_id,
            "version": self.version,
            "work_kind": self.work_kind.value,
            "timezone": self.timezone,
            "target_times": sorted(self.target_times),
            "cadence_minutes": self.cadence_minutes,
            "activation_epoch": self.activation_epoch.isoformat(),
            "max_lateness_hours": self.max_lateness_hours,
            "app_config_path": self.app_config_path,
            "data_root": self.data_root,
            "assessment_mode": self.assessment_mode,
            "llm_strategy": self.llm_strategy,
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        if not self.definition_hash:
            object.__setattr__(self, "definition_hash", self.compute_hash())


class ScheduleOccurrence(ContractModel):
    """Durable occurrence tracking for a scheduled calendar slot."""

    occurrence_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    deployment_id: str
    schedule_id: str
    definition_version: int
    work_kind: ScheduleKind
    intended_slot: str = Field(description="Formatted local intent string e.g. '2026-10-31T07:00:00 Europe/Berlin'")
    intended_utc_instant: UtcDatetime
    local_offset_minutes: int
    fold: int = Field(default=0, ge=0, le=1)
    outcome: OccurrenceOutcome = Field(default=OccurrenceOutcome.DUE)
    admitted_run_id: uuid.UUID | None = None
    admitted_request_id: uuid.UUID | None = None
    retry_count: int = Field(default=0, ge=0)
    next_eligible_at: UtcDatetime | None = None
    terminal_at: UtcDatetime | None = None
    details_json: dict[str, Any] | None = None
    created_at: UtcDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: UtcDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LaunchAttemptRecord(ContractModel):
    """Durable diagnostic record of a single execution launch attempt."""

    launch_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    occurrence_id: uuid.UUID | None = None
    deployment_id: str
    schedule_id: str
    work_kind: ScheduleKind
    task_identity: str
    started_at: UtcDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: UtcDatetime | None = None
    bootstrap_status: BootstrapCategory = Field(default=BootstrapCategory.OK)
    readiness_message: str | None = None
    child_pid: int | None = None
    child_exit_code: int | None = None
    outcome: str = Field(description="Result outcome: success, busy, failed, partial, timeout, access_denied")
    application_run_id: uuid.UUID | None = None
    report_summary_json: dict[str, Any] | None = None
    sanitized_error: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None


class IdentityResourceManifest(ContractModel):
    """Manifest documenting execution identity, absolute paths, and ACLs (non-secret)."""

    account_name: str = Field(description="Executing Windows user name")
    account_sid: str | None = Field(default=None, description="Windows Security Identifier (SID)")
    logon_type: str = Field(default="Password", description="Windows Task logon type: Password or InteractiveToken")
    python_executable: str = Field(description="Absolute path to Python interpreter")
    package_root: str = Field(description="Absolute path to repository or installed package root")
    data_root: str = Field(description="Absolute path to runtime data root")
    app_config_path: str = Field(description="Absolute path to application configuration")
    model_service_url: str = Field(default="http://127.0.0.1:11434")
    model_binary_path: str | None = None
    model_name: str | None = None
    is_batch_logon_verified: bool = Field(default=False)
    acl_matrix: dict[str, str] = Field(default_factory=dict, description="Path -> Access permission description")


class ReadinessProbeResult(ContractModel):
    """Result of a model supervisor health and readiness probe."""

    is_ready: bool
    category: BootstrapCategory
    details: str
    installed_models: list[str] = Field(default_factory=list)
    latency_ms: float | None = None


class SchedulingSettings(ContractModel):
    """Configuration settings file representation for scheduling."""

    deployment_id: str = Field(default="default", description="Stable deployment identity")
    enabled: bool = Field(default=False, description="Master scheduling activation toggle")
    timezone: str = Field(default="Europe/Berlin", description="IANA timezone")
    schedules: list[ScheduleDefinition] = Field(default_factory=list)
    identity: IdentityResourceManifest | None = None


class DispatchReport(ContractModel):
    """Execution summary returned by the scheduling dispatcher."""

    status: str = Field(description="Dispatcher outcome status: success, idle, busy, partial, failed, disabled")
    exit_code: int = Field(description="Process exit code convention")
    message: str = Field(description="Human-readable execution summary")
    occurrence_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    launch_id: uuid.UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)

