"""C04 FetchManifest, C05 RawPosting / SourceJobDraft, and C06 NormalizedPosting contracts.

Enforces uniform schema structure while preserving raw source provenance.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    CompensationProvenance,
    EmploymentType,
    FetchOutcome,
    InventorySemantics,
    SalaryPeriod,
    WorkplaceType,
)
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import (
    ContentHash,
    SourceKey,
    UtcDatetime,
)


# ===================================================================
# C04 FetchManifest
# ===================================================================


class FetchManifest(ContractModel):
    """C04 Fetch Manifest.

    Records the execution and observed results of a fetch operation.
    Only successful complete inventory of the same scope can support
    disappearance inference downstream.
    """

    run_id: uuid.UUID = Field(description="Pipeline run UUID")
    source_key: str = Field(min_length=1, description="Source config identifier")
    scope_id: str = Field(min_length=1, description="Scope of this fetch (board, category, or query)")
    start_time: UtcDatetime = Field(description="Fetch start timestamp (UTC)")
    end_time: UtcDatetime = Field(description="Fetch completion timestamp (UTC)")
    cursor_in: str | None = Field(default=None, description="Input pagination cursor / page offset")
    cursor_out: str | None = Field(default=None, description="Output pagination cursor for resumption")
    page_count: int = Field(ge=0, description="Number of pages fetched")
    raw_response_refs: list[str] = Field(
        default_factory=list,
        description="References to stored raw response files or hashes",
    )
    observed_posting_identities: list[str] = Field(
        default_factory=list,
        description="List of provider-scoped posting IDs observed in this fetch",
    )
    outcome: FetchOutcome = Field(description="Outcome of the fetch: complete, partial, or failed")
    inventory_semantics: InventorySemantics = Field(
        description="Inventory semantics of the source being fetched",
    )
    error: ClassifiedError | None = Field(
        default=None,
        description="Error details if the fetch failed or partially failed",
    )


# ===================================================================
# C05 RawPosting & SourceJobDraft
# ===================================================================


class RawPosting(ContractModel):
    """C05 Raw Posting.

    Preserves unaltered raw response content with source identity and hash.
    Allows malformed upstream data to be preserved as evidence.
    """

    raw_payload_ref: str = Field(
        min_length=1, description="Local path or storage reference for raw payload"
    )
    raw_content_hash: ContentHash = Field(description="SHA-256 hash of the raw payload bytes")
    source_key: SourceKey = Field(description="Scoped source identity")
    fetch_time: UtcDatetime = Field(description="When the raw posting was fetched (UTC)")
    raw_headers: dict[str, str] | None = Field(
        default=None, description="Raw HTTP response headers if available"
    )
    raw_payload: str = Field(description="Raw payload text (JSON or HTML)")


class SourceJobDraft(ContractModel):
    """C05 Source Job Draft.

    Candidate fields mapped from source; extracts source structure without
    silently resolving company/job identity or fabricating missing facts.
    """

    raw_reference: str = Field(min_length=1, description="Reference to the raw posting")
    source_key: SourceKey = Field(description="Scoped source identity")
    fetch_time: UtcDatetime = Field(description="Fetch timestamp (UTC)")
    original_fields: dict[str, Any] = Field(
        description="Parsed source dictionary retaining original structure"
    )
    source_mapped_fields: dict[str, Any] = Field(
        description="Candidate fields mapped from source without normalization"
    )


# ===================================================================
# C06 NormalizedPosting
# ===================================================================


class StructuredLocation(ContractModel):
    """Structured location preserving original raw text.

    A single job posting may have multiple locations.
    """

    raw_text: str = Field(min_length=1, description="Original unparsed location string")
    country: str | None = Field(
        default=None, description="ISO 3166-1 alpha-2 country code (e.g. 'DE')"
    )
    region: str | None = Field(
        default=None, description="Sub-national region or Bundesland (e.g. 'Berlin')"
    )
    city: str | None = Field(default=None, description="City name")
    postal_code: str | None = Field(default=None, description="Postal / ZIP code")


class JobCompensation(ContractModel):
    """Compensation details retaining currency, period, and provenance.

    No implicit annualization or cross-currency conversion is performed.
    """

    min_amount: Decimal | None = Field(default=None, description="Minimum compensation amount")
    max_amount: Decimal | None = Field(default=None, description="Maximum compensation amount")
    currency: str = Field(default="EUR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    period: SalaryPeriod = Field(default=SalaryPeriod.YEARLY)
    is_gross: bool | None = Field(
        default=None, description="True if gross, False if net, None if unknown"
    )
    provenance: CompensationProvenance = Field(
        default=CompensationProvenance.UNKNOWN,
        description="Whether compensation is employer-provided or estimated",
    )


class NormalizedPosting(ContractModel):
    """C06 Normalized Posting.

    Uniform schema produced by common normalization. Missing title or usable
    source identity produces a validation issue, never a fabricated replacement.
    """

    source_key: SourceKey = Field(description="Scoped source identity")
    normalizer_version: str = Field(min_length=1, description="Version of the normalizer used")
    raw_reference: str = Field(min_length=1, description="Reference to raw posting data")
    raw_content_hash: ContentHash = Field(description="SHA-256 hash of raw input content")
    company_name_hint: str = Field(min_length=1, description="Extracted company name hint")
    company_id_hint: str | None = Field(
        default=None, description="Provider-scoped company/employer ID if present"
    )
    title: str = Field(min_length=1, description="Job title; required")
    description_clean: str = Field(
        min_length=1, description="Cleaned, HTML-stripped description text"
    )
    source_url: str = Field(min_length=1, description="Original posting source URL")
    application_url: str | None = Field(
        default=None, description="Direct application URL if distinct from source URL"
    )
    locations: list[StructuredLocation] = Field(
        default_factory=list,
        description="Structured locations preserving original text",
    )
    workplace_type: WorkplaceType = Field(
        default=WorkplaceType.UNKNOWN,
        description="Onsite, hybrid, remote, or unknown",
    )
    remote_eligibility_restrictions: list[str] = Field(
        default_factory=list,
        description="Geographic restrictions on remote eligibility (e.g. ['DE', 'EU'])",
    )
    employment_type: EmploymentType = Field(
        default=EmploymentType.UNKNOWN,
        description="Full-time, part-time, contract, internship, etc.",
    )
    compensation: JobCompensation | None = Field(
        default=None,
        description="Structured compensation; null if unstated in advert",
    )
    advert_language: str | None = Field(
        default=None,
        description="Detected or declared advert language code (e.g. 'de', 'en')",
    )
    source_published_at: UtcDatetime | None = Field(
        default=None,
        description="Publication timestamp stated by the source (UTC)",
    )
    source_updated_at: UtcDatetime | None = Field(
        default=None,
        description="Last update timestamp stated by the source (UTC)",
    )
    source_deadline_at: UtcDatetime | None = Field(
        default=None,
        description="Application closing date stated by the source; null if absent",
    )
    observed_at: UtcDatetime = Field(
        description="Locally observed timestamp when this posting was fetched/processed",
    )
    field_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Provenance mapping for individual fields (e.g. {'title': 'raw.job_title'})",
    )

