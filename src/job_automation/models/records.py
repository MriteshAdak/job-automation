"""Data contracts and audit records for model invocation (LLM-01-S01).

Follows FND-01 ContractModel conventions:
- frozen=True
- extra="forbid"
- schema_version="1.0"
- UTC datetime validation
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.models import TokenUsage
from job_automation.contracts.primitives import UtcDatetime


class BoundGenerationInput(ContractModel):
    """Immutable bound generation input keyed by call_id and input_fingerprint."""

    call_id: uuid.UUID = Field(description="Unique call UUID matching ModelCall.call_id")
    prompt: str = Field(min_length=1, description="Caller-prepared user prompt or data content")
    system_prompt: str | None = Field(
        default=None,
        description="Optional system prompt or persona instructions",
    )
    input_fingerprint: str = Field(
        min_length=1,
        description="Canonical input fingerprint verifying prompt integrity",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret caller metadata (e.g. prompt template tags)",
    )


class BoundEmbeddingInput(ContractModel):
    """Immutable bound embedding input keyed by call_id and input_fingerprint."""

    call_id: uuid.UUID = Field(description="Unique call UUID for this embedding batch")
    texts: list[str] = Field(min_length=1, description="Ordered non-empty texts to embed")
    input_fingerprint: str = Field(
        min_length=1,
        description="Canonical input fingerprint over ordered texts",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret caller metadata",
    )


class AttemptAuditRecord(ContractModel):
    """Audit record for an individual physical transport attempt."""

    call_id: uuid.UUID = Field(description="UUID linking to logical call")
    attempt_number: int = Field(ge=1, description="1-based attempt sequence number")
    purpose: str = Field(
        description="Attempt purpose: 'initial', 'retry_service', or 'regeneration_malformed_output'",
    )
    start_time_utc: UtcDatetime = Field(description="Attempt start timestamp in UTC")
    end_time_utc: UtcDatetime = Field(description="Attempt completion timestamp in UTC")
    duration_ms: float = Field(ge=0.0, description="Elapsed attempt duration in milliseconds")
    http_status: int | None = Field(default=None, description="HTTP response code if reached")
    outcome: str = Field(description="'success' or classified error category")
    error_code: str | None = Field(default=None, description="Specific error classification code")
    token_usage: TokenUsage | None = Field(default=None, description="Token usage for this attempt")


class LogicalCallAuditRecord(ContractModel):
    """Complete audit record for a logical generation or embedding call."""

    call_id: uuid.UUID = Field(description="Unique call UUID")
    operation_type: str = Field(description="Operation type (e.g. 'relevance_assessment', 'embedding')")
    requested_model: str = Field(description="Requested model identifier")
    requested_digest: str | None = Field(default=None, description="Requested model digest if pinned")
    observed_model: str | None = Field(default=None, description="Observed model from runtime")
    observed_digest: str | None = Field(default=None, description="Observed digest from runtime")
    prompt_version: str | None = Field(default=None, description="Prompt version if generation")
    system_prompt_version: str | None = Field(default=None, description="System prompt version if separated")
    input_format_version: str | None = Field(default=None, description="Input format version (e.g. 'v1' for embedding)")
    schema_id: str | None = Field(default=None, description="Requested output schema ID")
    schema_version: str | None = Field(default=None, description="Output schema version")
    effective_settings: dict[str, Any] = Field(
        default_factory=dict,
        description="Effective execution settings applied",
    )
    context_limit: int = Field(gt=0, description="Effective context window limit")
    input_fingerprint: str = Field(description="Canonical fingerprint of input")
    fingerprint_algorithm: str = Field(default="sha256", description="Fingerprint hash algorithm")
    fingerprint_version: str = Field(default="v1", description="Fingerprint encoding version")
    budget_method: str = Field(default="conservative_v1", description="Context budget counting/estimation method")
    start_time_utc: UtcDatetime = Field(description="Logical call start timestamp in UTC")
    end_time_utc: UtcDatetime = Field(description="Logical call end timestamp in UTC")
    latency_ms: float = Field(ge=0.0, description="Total logical elapsed latency in milliseconds")
    token_usage: TokenUsage | None = Field(default=None, description="Aggregate or final token usage")
    outcome: str = Field(description="'success' or classified error category")
    error_code: str | None = Field(default=None, description="Specific failure reason code")
    attempts_count: int = Field(ge=0, description="Total physical transport attempts executed")
    attempts: list[AttemptAuditRecord] = Field(
        default_factory=list,
        description="Audit records for each physical attempt",
    )

