"""Domain and contract models for source registry and selection (SOURCE-01).

Preserves identity, access review, attribution, request policy, and inventory scope
using the existing C03 SourceConfig contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.sources import SourceConfig


class SourceRegistryEnvelope(ContractModel):
    """Versioned JSON envelope containing C03 SourceConfig records."""

    schema_version: str = Field(
        default="1.0",
        description="Schema version of source registry envelope",
    )
    sources: list[SourceConfig] = Field(
        default_factory=list,
        description="Configured source configurations",
    )


class AccessReviewStatus(str, Enum):
    """Status of documented access authorization review."""

    UNREVIEWED = "unreviewed"
    PERMITTED = "permitted"
    DENIED = "denied"


class AccessReview(ContractModel):
    """Structured access review metadata preserving documented permission evidence."""

    status: AccessReviewStatus = Field(
        default=AccessReviewStatus.UNREVIEWED,
        description="Reviewed authorization status: unreviewed, permitted, denied",
    )
    reviewed_at: str | None = Field(
        default=None,
        description="UTC ISO-8601 timestamp when review was recorded",
    )
    evidence_ref: str | None = Field(
        default=None,
        description="Reference to documented terms, license, or written permission",
    )
    permitted_methods: list[AcquisitionMethod] = Field(
        default_factory=list,
        description="List of acquisition methods explicitly authorized by evidence",
    )
    restrictions: list[str] = Field(
        default_factory=list,
        description="Documented operational or usage restrictions",
    )
    notes: str | None = Field(
        default=None,
        description="Reviewer notes or original access rules prose",
    )


class AttributionStatus(str, Enum):
    """Attribution requirement status."""

    UNKNOWN = "unknown"
    REQUIRED = "required"
    NONE_REQUIRED = "none_required"


class AttributionReview(ContractModel):
    """Preserved attribution and notice requirements."""

    status: AttributionStatus = Field(
        default=AttributionStatus.UNKNOWN,
        description="Attribution state: unknown, required, or none_required",
    )
    notice: str | None = Field(
        default=None,
        description="Required attribution notice text",
    )
    link: str | None = Field(
        default=None,
        description="Required attribution URL or credit link",
    )
    notes: str | None = Field(
        default=None,
        description="Preserved notes or original attribution rules prose",
    )


class EffectiveRequestPolicy(ContractModel):
    """Finite typed interpretation of C03 request_policy dictionary."""

    timeout_seconds: float = Field(
        default=30.0,
        description="Request timeout in seconds (> 0)",
    )
    request_spacing_seconds: float | None = Field(
        default=None,
        description="Minimum seconds between sequential requests (>= 0)",
    )
    max_attempts: int = Field(
        default=1,
        description="Maximum attempts including initial request (>= 1)",
    )
    backoff_factor: float = Field(
        default=1.0,
        description="Exponential backoff factor in seconds (>= 0)",
    )
    backoff_max_seconds: float = Field(
        default=30.0,
        description="Upper bound cap on backoff wait (>= backoff_factor)",
    )
    max_pages: int | None = Field(
        default=None,
        description="Budget cap on maximum pages per run (>= 1)",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Allowlisted non-secret HTTP request headers",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Allowlisted non-secret query parameters",
    )
    credential_ref: str | None = Field(
        default=None,
        description="Reference identifier for external credential lookup",
    )


class InventoryScope(ContractModel):
    """Deterministic inventory scope descriptor and stable scope identity."""

    scope_id: str = Field(
        description="Deterministic scope identifier: scope-v1:sha256:<hex64>",
    )
    semantics: InventorySemantics = Field(
        description="Coverage semantics: complete_board, filtered_feed, or search_results",
    )
    provider: str = Field(description="Normalized provider platform name")
    board_id: str = Field(description="Exact board or tenant identifier")
    acquisition_method: AcquisitionMethod = Field(description="Acquisition mechanism")
    base_url: str = Field(description="Normalized entry endpoint")
    query_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Membership-affecting query parameters",
    )
    scope_filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Explicit scope filters affecting inventory membership",
    )
    completeness_evidence: str | None = Field(
        default=None,
        description="Documented basis for complete-board coverage assertion",
    )


class EffectiveSource(ContractModel):
    """Validated source configuration preserving C03 and derived effective metadata."""

    config: SourceConfig = Field(
        description="Original C03 SourceConfig contract instance",
    )
    access_review: AccessReview = Field(
        description="Structured access review metadata",
    )
    attribution_review: AttributionReview = Field(
        description="Structured attribution requirements",
    )
    request_policy: EffectiveRequestPolicy = Field(
        description="Validated effective request policy",
    )
    inventory_scope: InventoryScope = Field(
        description="Derived deterministic inventory scope",
    )
    is_valid: bool = Field(
        default=True,
        description="Whether source configuration passed semantic validation",
    )
    is_runnable: bool = Field(
        default=False,
        description="Whether source is enabled, permitted, and ready for execution",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="Validation issues and warnings",
    )
    readiness_blockers: list[str] = Field(
        default_factory=list,
        description="Human-readable blockers preventing execution",
    )


class SourceSelectionResult(ContractModel):
    """Result of source selection and preflight validation."""

    selected_sources: list[EffectiveSource] = Field(
        default_factory=list,
        description="Selected runnable sources (empty if any requested key is blocked)",
    )
    all_sources: dict[str, EffectiveSource] = Field(
        default_factory=dict,
        description="All configured sources in registry keyed by source_key",
    )
    requested_keys: list[str] = Field(
        default_factory=list,
        description="List of source keys requested for selection",
    )
    is_valid: bool = Field(
        default=True,
        description="Whether requested selection is valid and runnable",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Blocker messages explaining why selection failed",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="Validation issues across requested sources",
    )

