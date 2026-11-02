"""GEN-06 delivery contracts and value objects (R12, R16).

Defines:
- Immutable DeliveryIntent and audit DeliveryAttempt records.
- RemoteArtifactMapping binding local artifacts to Salesforce Files (ContentDocument/ContentVersion).
- AccessibilityReceipt ensuring candidate-accessible files before readiness.
- DeliverySetReceipt sealing delivery of all required formats.
- ReviewProjection and ReadinessTransitionRecord for safe progress and notification boundaries.
- Reconciliation marker grammar: gen06:v1:<request_uuid>:<artifact_uuid>:<artifact_version>
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import ContentHash, UtcDatetime


def _canonical_json_dumps(data: Any) -> str:
    def _default(obj: Any) -> Any:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.astimezone(timezone.utc).isoformat()
        if hasattr(obj, "value"):
            return obj.value
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    return json.dumps(data, default=_default, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_sha256_digest(data: Any) -> str:
    """Compute sha256:<hex> content digest over canonical JSON payload."""
    payload = _canonical_json_dumps(data)
    hex_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{hex_digest}"


# Marker regex pattern: gen06:v1:<request_uuid>:<artifact_uuid>:<artifact_version>
MARKER_REGEX = re.compile(
    r"^gen06:v1:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}:[0-9]+$"
)

DeliveryIntentStatus = Literal[
    "pending",
    "sending",
    "uncertain",
    "uploaded",
    "linked",
    "accessible",
    "delivered",
    "failed",
    "blocked",
]

DeliveryOperationKind = Literal["upload", "query", "link", "access", "download"]

DeliveryPhase = Literal[
    "prepared",
    "sending",
    "uncertain",
    "uploaded",
    "linking",
    "checking_access",
    "delivered",
    "blocked",
]


def build_reconciliation_marker(
    request_id: uuid.UUID,
    artifact_id: uuid.UUID,
    artifact_version: int,
) -> str:
    """Format standard reconciliation marker."""
    if artifact_version < 1:
        raise ValueError("artifact_version must be >= 1")
    return f"gen06:v1:{request_id}:{artifact_id}:{artifact_version}"


def parse_reconciliation_marker(marker: str) -> tuple[uuid.UUID, uuid.UUID, int]:
    """Parse and validate standard reconciliation marker."""
    if not MARKER_REGEX.match(marker):
        raise ValueError(
            f"Invalid reconciliation marker '{marker}'. Must match 'gen06:v1:<request_id>:<artifact_id>:<version>'"
        )
    parts = marker.split(":")
    return uuid.UUID(parts[2]), uuid.UUID(parts[3]), int(parts[4])


class DeliveryIntent(ContractModel):
    """Committed durable intent to deliver an artifact to Salesforce Files before physical send."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"

    intent_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    org_id: str = Field(min_length=15, max_length=18)
    salesforce_request_id: str = Field(min_length=15, max_length=18)
    canonical_salesforce_id: str | None = Field(default=None, min_length=15, max_length=18)
    request_id: uuid.UUID
    artifact_set_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_version: int = Field(default=1, ge=1)
    artifact_format: Literal["docx", "pdf"]
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    local_path: str = Field(min_length=1)
    reconciliation_marker: str
    status: DeliveryIntentStatus = "pending"
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @field_validator("reconciliation_marker")
    @classmethod
    def validate_marker(cls, v: str) -> str:
        if not MARKER_REGEX.match(v):
            raise ValueError(f"Invalid reconciliation marker grammar: {v}")
        return v

    @property
    def logical_key(self) -> str:
        """Unique logical key per org, request, artifact, and version."""
        return f"{self.org_id}:{self.request_id}:{self.artifact_id}:{self.artifact_version}"


class DeliveryAttempt(ContractModel):
    """Physical execution audit trace for an upload, query, link, or access check."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"

    attempt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    intent_id: uuid.UUID
    request_id: uuid.UUID
    attempt_sequence: int = Field(ge=1)
    operation_kind: DeliveryOperationKind
    phase: DeliveryPhase
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    status: Literal["started", "completed", "failed", "uncertain"] = "started"
    exit_code: int | None = None
    duration_ms: int | None = None
    error_json: dict[str, Any] | None = None
    outcome_evidence: dict[str, Any] | None = None


class RemoteArtifactMapping(ContractModel):
    """Authoritative binding between local artifact and Salesforce ContentDocument/ContentVersion."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"

    mapping_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    intent_id: uuid.UUID
    request_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_version: int = Field(ge=1)
    artifact_format: Literal["docx", "pdf"]
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    org_id: str = Field(min_length=15, max_length=18)
    content_document_id: str = Field(min_length=15, max_length=18)
    content_version_id: str = Field(min_length=15, max_length=18)
    provider_version_label: str | None = None
    marker: str
    target_record_id: str = Field(min_length=15, max_length=18)
    link_id: str | None = Field(default=None, min_length=15, max_length=18)
    acknowledged_at: UtcDatetime

    @field_validator("marker")
    @classmethod
    def validate_marker(cls, v: str) -> str:
        if not MARKER_REGEX.match(v):
            raise ValueError(f"Invalid reconciliation marker grammar: {v}")
        return v


class AccessibilityReceipt(ContractModel):
    """Cryptographic and contextual proof that a delivered file is candidate-accessible."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"

    receipt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    mapping_id: uuid.UUID
    request_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_version: int = Field(ge=1)
    artifact_format: Literal["docx", "pdf"]
    content_version_id: str = Field(min_length=15, max_length=18)
    content_document_id: str = Field(min_length=15, max_length=18)
    target_record_id: str = Field(min_length=15, max_length=18)
    verification_method: Literal[
        "direct_download", "sharing_policy_check", "mock_verification"
    ]
    candidate_principal: str | None = None
    verified_at: UtcDatetime
    receipt_hash: str = Field(default="")

    def model_post_init(self, __context: Any) -> None:
        if not self.receipt_hash:
            data = self.model_dump(exclude={"receipt_hash"})
            digest = compute_sha256_digest(data)
            object.__setattr__(self, "receipt_hash", digest)


class DeliverySetReceipt(ContractModel):
    """Receipt proving all required formats of an ArtifactSet have been delivered and verified accessible."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"

    set_receipt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    set_id: uuid.UUID
    set_version: int = Field(ge=1)
    required_formats: list[Literal["docx", "pdf"]]
    mappings: dict[str, RemoteArtifactMapping] = Field(default_factory=dict)
    accessibility_receipts: dict[str, AccessibilityReceipt] = Field(default_factory=dict)
    is_accessible: bool = False
    review_route: str = Field(min_length=1)
    created_at: UtcDatetime
    receipt_hash: str = Field(default="")

    def model_post_init(self, __context: Any) -> None:
        all_mapped = all(fmt in self.mappings for fmt in self.required_formats)
        all_accessible = all(fmt in self.accessibility_receipts for fmt in self.required_formats)
        complete = all_mapped and all_accessible
        object.__setattr__(self, "is_accessible", complete)
        if not self.receipt_hash:
            data = self.model_dump(exclude={"receipt_hash"})
            digest = compute_sha256_digest(data)
            object.__setattr__(self, "receipt_hash", digest)


class ReviewProjection(ContractModel):
    """Review presentation package delivered to Salesforce Generation_Request__c."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"

    request_id: uuid.UUID
    salesforce_request_id: str = Field(min_length=15, max_length=18)
    set_version: int = Field(ge=1)
    result_version_refs: dict[str, str] = Field(
        description="Format -> ContentVersion ID mapping"
    )
    result_document_refs: dict[str, str] = Field(
        description="Format -> ContentDocument ID mapping"
    )
    review_warnings: list[str] = Field(default_factory=list)
    semantic_limits_notice: str = (
        "Draft generated by automated pipeline. Review claims, dates, and subjective phrasing "
        "before formal approval or job submission."
    )
    predecessor_request_id: uuid.UUID | None = None
    predecessor_version_refs: dict[str, str] | None = None
    delivered_at: UtcDatetime


class ReadinessTransitionRecord(ContractModel):
    """Record representing a single, un-replayable transition to Ready_for_Review for SF-08 consumption."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"

    transition_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    salesforce_request_id: str = Field(min_length=15, max_length=18)
    readiness_key: str = Field(
        min_length=1,
        description="Deterministic transition identity: ready:<request_id>:<set_version>:<set_hash>",
    )
    desired_remote_state: Literal["Ready_for_Review"] = "Ready_for_Review"
    projection_revision: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    transitioned_at: UtcDatetime
