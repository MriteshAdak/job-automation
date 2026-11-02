"""Ingestion models, options, receipts, and stage results (INGEST-01-S01).

Defines versioned local models for:
- ControllerOptions / FetchLimits: bounded runtime budgets and policies
- AttemptRecord: single HTTP/adapter attempt telemetry
- PageReceipt: auditable receipt of one fetched or cached page
- SourceCheckpoint: durable checkpoint state for traversal resumption
- SourceFetchResult: single-source fetch execution summary and manifest
- FetchStageResult: aggregate multi-source fetch stage summary for RUN-01
- CacheEntry: metadata and payload references for safe page caching
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.enums import FetchOutcome
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.postings import FetchManifest, RawPosting
from job_automation.contracts.primitives import UtcDatetime


class ControllerOptions(BaseModel):
    """Explicit runtime controller options and finite budgets.

    Provides finite defaults so no unconstrained automated run can occur.
    More restrictive source or caller caps take precedence.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", description="Options schema version")
    max_pages: int = Field(default=10, ge=1, description="Maximum logical pages to fetch per source")
    max_requests: int = Field(default=20, ge=1, description="Maximum outbound HTTP requests per source")
    max_attempts_per_page: int = Field(
        default=3, ge=1, description="Maximum attempts per logical page (including initial)"
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0.0, description="Transport timeout in seconds per request"
    )
    source_deadline_seconds: float = Field(
        default=300.0, gt=0.0, description="Overall wall-clock/monotonic deadline per source"
    )
    max_response_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1, description="Maximum allowed response size in bytes (10 MiB)"
    )
    request_spacing_seconds: float = Field(
        default=0.0, ge=0.0, description="Minimum delay between outbound requests to same origin"
    )
    backoff_factor: float = Field(
        default=1.0, ge=0.0, description="Multiplier for exponential backoff between retries"
    )
    backoff_max_seconds: float = Field(
        default=30.0, ge=0.0, description="Maximum backoff delay ceiling in seconds"
    )
    cache_mode: str = Field(
        default="disabled", description="Cache mode: 'disabled' or 'ttl'"
    )
    cache_ttl_seconds: int = Field(
        default=0, ge=0, description="Cache time-to-live in seconds (0 = disabled)"
    )
    input_base_path: Path | None = Field(
        default=None, description="Explicit base path for manual file imports"
    )
    manual_inputs: dict[str, Any] = Field(
        default_factory=dict, description="Manual source input configurations keyed by source_key"
    )

    @field_validator("cache_mode")
    @classmethod
    def validate_cache_mode(cls, v: str) -> str:
        if v not in {"disabled", "ttl"}:
            raise ValueError(f"Unsupported cache_mode '{v}'; must be 'disabled' or 'ttl'")
        return v

    @field_validator("max_pages", "max_requests", "max_attempts_per_page", mode="before")
    @classmethod
    def reject_bool_as_int(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not valid integer caps")
        return v


class AttemptRecord(BaseModel):
    """Telemetry and outcome of a single request/page fetch attempt."""

    model_config = ConfigDict(extra="forbid")

    attempt_number: int = Field(ge=1, description="1-based attempt index for current page")
    started_at: UtcDatetime = Field(description="Attempt start timestamp (UTC)")
    duration_ms: float = Field(ge=0.0, description="Attempt elapsed duration in milliseconds")
    status_code: int | None = Field(default=None, description="HTTP response status code if available")
    error: ClassifiedError | None = Field(default=None, description="Classified error if attempt failed")
    retry_after_seconds: float | None = Field(
        default=None, ge=0.0, description="Parsed Retry-After delay if provided by server"
    )


class PageReceipt(BaseModel):
    """Auditable receipt for a single logical page processed by the controller."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", description="Receipt schema version")
    traversal_id: str = Field(description="Unique traversal execution identifier")
    page_index: int = Field(ge=1, description="1-based logical page position in traversal")
    attempt_count: int = Field(ge=1, description="Number of attempts made for this page")
    continuation_in: Continuation | None = Field(
        default=None, description="Input continuation token used for this page"
    )
    continuation_out: Continuation | None = Field(
        default=None, description="Output continuation token returned by adapter"
    )
    source_key: str = Field(description="Source identifier")
    scope_id: str = Field(description="Scope identifier")
    adapter_name: str = Field(description="Adapter identifier")
    raw_response_refs: list[str] = Field(
        default_factory=list, description="References to stored parent raw response payloads"
    )
    raw_response_hashes: list[str] = Field(
        default_factory=list, description="Content hashes of stored raw response payloads"
    )
    observed_posting_ids: list[str] = Field(
        default_factory=list, description="Exact provider posting IDs observed on this page"
    )
    raw_record_refs: list[str] = Field(
        default_factory=list, description="References to individual raw record payloads/envelopes"
    )
    draft_results: list[DraftResult] = Field(
        default_factory=list, description="Draft mapping results for raw records on this page"
    )
    issues: list[RecordIssue] = Field(
        default_factory=list, description="All record issues (warnings & errors) on this page"
    )
    from_cache: bool = Field(default=False, description="True if page was served from local cache")
    fetch_time: UtcDatetime = Field(description="UTC timestamp of page capture")
    exhausted: bool = Field(default=False, description="True if source indicated terminal exhaustion")
    truncated: bool = Field(default=False, description="True if page was cut short by limits")
    page_error: ClassifiedError | None = Field(
        default=None, description="Page-level error if fetch failed"
    )


class SourceCheckpoint(BaseModel):
    """Persistent checkpoint for resumable source traversal."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", description="Checkpoint schema version")
    traversal_id: str = Field(description="Unique traversal execution identifier")
    run_id: uuid.UUID = Field(description="Pipeline run UUID")
    source_key: str = Field(description="Source identifier")
    scope_id: str = Field(description="Scope identifier")
    adapter_name: str = Field(description="Adapter identifier")
    initial_cursor_in: Continuation | None = Field(
        default=None, description="Original cursor used at the start of this traversal"
    )
    current_continuation: Continuation | None = Field(
        default=None, description="Next continuation token to execute, or None if terminal"
    )
    visited_tokens: list[str] = Field(
        default_factory=list, description="Serialized continuation tokens visited to detect cycles"
    )
    pages_completed: int = Field(ge=0, default=0, description="Number of logical pages successfully committed")
    records_observed: list[str] = Field(
        default_factory=list, description="Unique posting IDs in stable first-observation order"
    )
    raw_response_refs: list[str] = Field(
        default_factory=list, description="Distinct parent raw response references committed"
    )
    requests_made: int = Field(ge=0, default=0, description="Outbound requests consumed so far")
    created_at: UtcDatetime = Field(description="Checkpoint creation timestamp (UTC)")
    updated_at: UtcDatetime = Field(description="Checkpoint last update timestamp (UTC)")


class CacheEntry(BaseModel):
    """Stored cache item representing a previously fetched and verified page."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", description="Cache entry schema version")
    cache_key: str = Field(description="Deterministic content/query cache key")
    source_key: str = Field(description="Source identifier")
    scope_id: str = Field(description="Scope identifier")
    adapter_name: str = Field(description="Adapter identifier")
    continuation_token: str | None = Field(default=None, description="Serialized continuation token")
    raw_response_refs: list[str] = Field(description="References to immutable raw payload files")
    raw_response_hashes: list[str] = Field(description="Expected hashes for payload verification")
    adapter_page_json: str = Field(description="Serialized AdapterPage contract")
    draft_results_json: str = Field(description="Serialized list of DraftResult contracts")
    captured_at: UtcDatetime = Field(description="Original capture timestamp (UTC)")
    expires_at: UtcDatetime = Field(description="Expiration timestamp (UTC)")


class SourceFetchResult(BaseModel):
    """Execution outcome and manifest for a single source."""

    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(description="Source identifier")
    outcome: FetchOutcome = Field(description="Outcome: complete, partial, or failed")
    manifest: FetchManifest = Field(description="Authoritative C04 FetchManifest")
    page_count: int = Field(ge=0, description="Number of logical pages fetched")
    observed_identities_count: int = Field(ge=0, description="Count of unique posting IDs observed")
    raw_records_count: int = Field(ge=0, description="Total raw record observations encountered")
    accepted_drafts_count: int = Field(ge=0, description="Drafts mapped without blocking errors")
    rejected_records_count: int = Field(ge=0, description="Records rejected due to blocking errors")
    warnings_count: int = Field(ge=0, description="Non-blocking warning issues recorded")
    requests_made: int = Field(ge=0, description="Network requests made for this source")
    from_cache_count: int = Field(ge=0, description="Pages retrieved from cache")
    error: ClassifiedError | None = Field(default=None, description="Terminal error if fetch failed")
    receipts: list[PageReceipt] = Field(default_factory=list, description="Ordered page receipts")


class FetchStageResult(BaseModel):
    """Aggregate summary of fetch stage execution across all sources for RUN-01."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", description="Stage summary schema version")
    run_id: uuid.UUID = Field(description="Pipeline run UUID")
    sources_attempted: int = Field(ge=0, default=0, description="Number of sources attempted")
    sources_completed: int = Field(ge=0, default=0, description="Number of sources with COMPLETE outcome")
    sources_partial: int = Field(ge=0, default=0, description="Number of sources with PARTIAL outcome")
    sources_failed: int = Field(ge=0, default=0, description="Number of sources with FAILED outcome")
    sources_not_attempted: int = Field(ge=0, default=0, description="Number of sources not attempted")
    total_requests: int = Field(ge=0, default=0, description="Total network requests across all sources")
    total_pages: int = Field(ge=0, default=0, description="Total logical pages fetched across all sources")
    total_raw_observations: int = Field(ge=0, default=0, description="Total raw record sightings")
    total_unique_identities: int = Field(ge=0, default=0, description="Total distinct posting IDs across all sources")
    source_results: dict[str, SourceFetchResult] = Field(
        default_factory=dict, description="Detailed results keyed by source_key"
    )
