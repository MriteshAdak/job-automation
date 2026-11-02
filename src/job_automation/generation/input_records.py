"""GEN-02 typed records, immutable input snapshot envelopes, and receipt contracts."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ConfigDict, Field

from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.selector_records import ContextSelectionResult
from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey, UtcDatetime
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.retrieval_index import EmbeddingConfiguration
from job_automation.generation.records import FreezeManifest


def canonical_json_dumps(data: Any) -> str:
    """Produce deterministic UTF-8 JSON serialization with sorted keys and normalized delimiters."""
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
    payload = canonical_json_dumps(data)
    hex_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{hex_digest}"


def compute_manifest_hash(manifest_data: dict[str, Any]) -> str:
    """Compute manifest hash excluding manifest_hash field itself."""
    clean = {k: v for k, v in manifest_data.items() if k != "manifest_hash"}
    return compute_sha256_digest(clean)


class FrozenGenerationOptions(ContractModel):
    """Canonicalized and validated generation options frozen at request acceptance."""

    schema_version: str = Field(default="1.0")
    document_type: DocumentType
    purpose: str = Field(description="Derived document purpose ('cv' or 'cover_letter')")
    target_language: str = Field(default="de")
    template_id: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    template_content_digest: str | None = None
    context_strategy: ContextStrategy = Field(default=ContextStrategy.JSON)
    allow_unavailable_job: bool = Field(default=False)
    override_provenance: str | None = None
    override_timestamp: UtcDatetime | None = None
    generation_settings: dict[str, Any] = Field(default_factory=dict)
    output_formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    options_digest: str = Field(min_length=1)


class FrozenJobSnapshot(ContractModel):
    """Exact frozen job posting content, revision binding, and identity metadata."""

    schema_version: str = Field(default="1.0")
    canonical_job_id: uuid.UUID
    company_name: str
    posting_revision_id: str = Field(min_length=1)
    posting_revision_hash: str = Field(min_length=1, description="Material content hash")
    raw_content_hash: str = Field(min_length=1, description="Raw C06 content hash")
    source_key: SourceKey
    normalized_posting: NormalizedPosting
    raw_reference: str | None = None
    source_url: str | None = None
    application_url: str | None = None
    observed_at: UtcDatetime
    first_seen_at: UtcDatetime
    last_seen_at: UtcDatetime
    normalizer_version: str = Field(default="v1")
    hash_algorithm_version: str = Field(default="v1")
    snapshot_digest: str = Field(min_length=1)


class FrozenProfileSnapshot(ContractModel):
    """Exact approved candidate profile facts, approval metadata, and purpose permissions."""

    schema_version: str = Field(default="1.0")
    candidate_id: uuid.UUID
    profile_version: str = Field(min_length=1)
    snapshot: ProfileSnapshot
    approved_by: str = Field(min_length=1)
    approved_at: UtcDatetime
    notes: str | None = None
    purpose: str = Field(min_length=1)
    inclusion_rule_version: str = Field(default="v1")
    mandatory_policy_version: str = Field(default="v1")
    explicit_mandatory_fact_ids: list[uuid.UUID] = Field(default_factory=list)
    eligible_fact_ids: list[uuid.UUID] = Field(default_factory=list)
    snapshot_digest: str = Field(min_length=1)


class AvailabilityCheck(ContractModel):
    """Durable receipt of the authoritative availability check at the time of sealing."""

    schema_version: str = Field(default="1.0")
    check_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    canonical_job_id: uuid.UUID
    checked_at: UtcDatetime
    canonical_availability: PostingAvailability
    explanation: str
    source_states: list[dict[str, Any]] = Field(default_factory=list)
    decision_outcome: str = Field(description="'proceed', 'proceed_with_warning', or 'rejected'")
    allow_unavailable_job: bool = Field(default=False)
    override_applied: bool = Field(default=False)
    override_provenance: str | None = None
    warnings: list[str] = Field(default_factory=list)
    earliest_seen: UtcDatetime | None = None
    latest_seen: UtcDatetime | None = None
    check_digest: str = Field(min_length=1)


class FrozenContextRecipe(ContractModel):
    """Frozen context assembly recipe, instructions, model parameters, and RAG configuration."""

    schema_version: str = Field(default="1.0")
    recipe_id: str = Field(min_length=1)
    recipe_version: str = Field(default="v1")
    instruction_text: str = Field(default="")
    output_schema_text: str | None = None
    requirements: list[str] = Field(default_factory=list)
    requirements_extraction_hash: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)
    context_limit: int = Field(gt=0)
    output_reserve: int = Field(default=512, ge=0)
    safety_allowance: int = Field(default=64, ge=0)
    require_exact_measurement: bool = Field(default=False)
    builder_version: str = Field(default="v1")
    serialization_version: str = Field(default="v1")
    inclusion_rule_version: str = Field(default="v1")
    mandatory_policy_version: str = Field(default="v1")
    template_name: str | None = None
    chat_template_version: str | None = None
    retrieval_settings: RetrievalSettings | None = None
    embedding_config: EmbeddingConfiguration | None = None
    recipe_digest: str = Field(min_length=1)
    content_recipe_json: str | None = None


class FrozenSeal(ContractModel):
    """Complete, immutable seal binding all inputs for a generation request."""

    schema_version: str = Field(default="1.0")
    seal_id: str = Field(min_length=1)
    request_id: uuid.UUID
    candidate_id: uuid.UUID
    canonical_job_id: uuid.UUID
    manifest: FreezeManifest
    options: FrozenGenerationOptions
    job_snapshot: FrozenJobSnapshot
    profile_snapshot: FrozenProfileSnapshot
    availability_check: AvailabilityCheck
    recipe: FrozenContextRecipe
    pinned_index_generation_id: uuid.UUID | None = None
    index_pin_id: uuid.UUID | None = None
    sealed_at: UtcDatetime
    seal_hash: str = Field(min_length=1)
    body_hash: str | None = None


class PreflightReceipt(ContractModel):
    """Audit receipt recording the outcome of input validation and availability preflight."""

    schema_version: str = Field(default="1.0")
    receipt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    accepted_options_digest: str = Field(min_length=1)
    freeze_op_id: str = Field(min_length=1)
    started_at: UtcDatetime
    completed_at: UtcDatetime
    result: str = Field(description="'prepared' or 'failed'")
    seal_id: str | None = None
    seal_hash: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: ClassifiedError | None = None
    reason_code: str | None = None


class FrozenContextReceipt(ContractModel):
    """Durable receipt and cached context selection result assembled strictly from frozen inputs."""

    schema_version: str = Field(default="1.0")
    receipt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    manifest_id: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    recipe_hash: str = Field(min_length=1)
    context_op_id: str = Field(min_length=1)
    result: ContextSelectionResult
    warnings: list[str] = Field(default_factory=list)
    result_hash: str = Field(min_length=1)
    created_at: UtcDatetime


class GenerationInputSettings(ContractModel):
    """Configuration settings for GEN-02 input freezing and context assembly."""

    schema_version: str = Field(default="1.0")
    candidate_id: uuid.UUID | None = None
    supported_languages: list[str] = Field(default_factory=lambda: ["de", "en"])
    supported_document_types: list[str] = Field(default_factory=lambda: ["cv", "cover_letter"])
    default_template_id: str = Field(default="default_template")
    default_template_version: str = Field(default="v1")
    default_model_identifier: str = Field(default="gemini-1.5-pro")
    default_context_limit: int = Field(default=8192)
    default_output_reserve: int = Field(default=512)
    default_safety_allowance: int = Field(default=64)
    require_exact_measurement: bool = Field(default=False)
    retrieval_settings: RetrievalSettings = Field(default_factory=RetrievalSettings)
    embedding_config: EmbeddingConfiguration | None = None
    default_instruction_text_cv: str = Field(
        default="Tailor the candidate CV directly to the target job posting."
    )
    default_instruction_text_cover_letter: str = Field(
        default="Draft a persuasive, professional cover letter grounded in verified candidate evidence."
    )

