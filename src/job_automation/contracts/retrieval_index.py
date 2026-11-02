"""Retrieval index contracts for CONTEXT-03.

Defines deterministic, versioned local retrieval index contracts:
- IndexSettings: Layout, format, matrix dtype, metric, analyzer options, and resource limits.
- EmbeddingConfiguration: Bound model identity, dimensions, prefix rules, and provenance.
- PayloadFileInfo: File path, size, and SHA-256 digest of stored index artifacts.
- IndexRowMapping: Mapping of row ordinal to chunk identity, content version, and C08 references.
- IndexManifest: Complete manifest describing an immutable generation on disk.
- IndexBuildRequest: Explicit bound request for index construction.
- IndexBuildRecord: Durable ledger record documenting the execution of an index build.
- IndexBuildResult: Outcome of an index build including generation manifest and activation token.
- IndexReadRequest: Consumer authorization and expected-binding request for index access.
- TermPosting: Inverted index entry with term, row ordinal, term frequency, and token positions.
- IndexPin: Pinning record preventing cleanup of retired generations in active use.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.evidence_chunks import ChunkChangeSet, ChunkSet
from job_automation.contracts.primitives import UtcDatetime


class IndexSettings(ContractModel):
    """Configuration, layout, and capacity limits for local vector and keyword indexing."""

    schema_version: str = "1.0"
    index_version: str = "v1"
    algorithm_version: str = "v1"
    format_version: str = "v1"
    canonicalization_version: str = "v1"

    # Vector matrix encoding & metric
    dtype: Literal["float32"] = "float32"
    byte_order: Literal["little_endian"] = "little_endian"
    metric: Literal["cosine", "dot_product", "euclidean"] = "cosine"
    normalization: Literal["l2", "none"] = "l2"

    # Keyword analyzer settings
    analyzer_version: str = "v1"
    analyzer_options: dict[str, Any] = Field(default_factory=dict)

    # Finite capacity & resource limits
    max_chunks: int = Field(default=10000, gt=0, description="Maximum chunks permitted in an index")
    max_dimension: int = Field(default=4096, gt=0, description="Maximum vector embedding dimension")
    max_text_bytes: int = Field(
        default=65536, gt=0, description="Maximum bytes for an individual chunk's retrieval_text"
    )
    max_build_memory_bytes: int = Field(
        default=1073741824, gt=0, description="Maximum estimated working memory for build (1 GB)"
    )
    max_disk_bytes: int = Field(
        default=10737418240, gt=0, description="Maximum disk space allocated for index storage (10 GB)"
    )
    max_build_time_seconds: float = Field(
        default=300.0, gt=0.0, description="Maximum wall-clock seconds for a full index build"
    )
    cleanup_retained_generations: int = Field(
        default=2, ge=0, description="Number of retired generations to retain for audit/recovery"
    )

    @field_validator("dtype")
    @classmethod
    def _validate_dtype(cls, v: str) -> str:
        if v != "float32":
            raise ValueError(f"Unsupported matrix dtype '{v}'. Only 'float32' is supported in v1.")
        return v

    @field_validator("byte_order")
    @classmethod
    def _validate_byte_order(cls, v: str) -> str:
        if v != "little_endian":
            raise ValueError(f"Unsupported byte_order '{v}'. Only 'little_endian' is supported in v1.")
        return v


class EmbeddingConfiguration(ContractModel):
    """Measured embedding model configuration, dimensions, and execution parameters."""

    schema_version: str = "1.0"
    configuration_version: str = "v1"

    model_identifier: str = Field(min_length=1, description="Model identifier or tag (e.g. nomic-embed-text)")
    dimension: int = Field(gt=0, description="Embedding vector dimension")
    model_digest: str | None = Field(
        default=None,
        description="Immutable SHA-256 digest of model weights/manifest if verified",
    )
    expected_digest: str | None = Field(
        default=None,
        description="Expected model digest configured for drift detection",
    )
    verification_provenance: str = Field(
        default="model_02_recommendation",
        description="Origin of verification (e.g. 'model_02_recommendation', 'synthetic_fake')",
    )

    runtime_version: str = Field(default="1.0", min_length=1)
    provider_version: str = Field(default="1.0", min_length=1)

    document_prefix: str = Field(
        default="",
        description="Prefix prepended to document chunks before embedding (e.g. 'search_document: ')",
    )
    query_prefix: str = Field(
        default="",
        description="Prefix prepended to query text before embedding (e.g. 'search_query: ')",
    )
    output_affecting_options: dict[str, Any] = Field(
        default_factory=dict,
        description="Options that affect numerical embedding output",
    )

    measurement_method: str = Field(
        default="character_ratio",
        description="Tokenizer or estimator method used for input measurement",
    )
    max_input_tokens: int = Field(
        default=512, gt=0, description="Maximum tokens per single text chunk"
    )
    max_batch_items: int = Field(
        default=32, gt=0, description="Maximum items per embedding API call"
    )
    max_batch_bytes: int = Field(
        default=1048576, gt=0, description="Maximum combined UTF-8 bytes per embedding batch"
    )

    model_02_report_ref: str | None = Field(
        default=None,
        description="Reference identifier or file path of MODEL-02 benchmark report",
    )
    model_02_report_hash: str | None = Field(
        default=None,
        description="SHA-256 content hash of MODEL-02 benchmark report",
    )


class PayloadFileInfo(ContractModel):
    """Physical file metadata within an index generation directory."""

    schema_version: str = "1.0"
    relative_path: str = Field(min_length=1, description="Path relative to generation directory")
    byte_length: int = Field(ge=0, description="Exact file size in bytes")
    sha256_hash: str = Field(min_length=64, max_length=64, description="SHA-256 hex digest of file content")


class IndexRowMapping(ContractModel):
    """Row ordinal alignment binding a vector and keyword document to an evidence chunk."""

    schema_version: str = "1.0"
    row_ordinal: int = Field(ge=0, description="0-based row index in matrix and keyword document id")
    chunk_id: uuid.UUID = Field(description="UUIDv5 of the evidence chunk")
    chunk_version: str = Field(min_length=1, description="Content version SHA-256 of the chunk")
    binding_fingerprint: str = Field(
        min_length=1, description="Binding fingerprint from the chunk set"
    )
    primary_fact_id: uuid.UUID = Field(description="UUID of the primary CandidateFact")
    primary_kind: EvidenceFactKind = Field(description="Kind of the primary fact")
    c08_references: list[CandidateEvidenceReference] = Field(
        default_factory=list,
        description="Fine-grained C08 references cited by this row",
    )
    parent_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="UUIDs of parent facts contributing to this chunk",
    )


class IndexManifest(ContractModel):
    """Complete manifest describing an immutable local index generation on disk."""

    schema_version: str = "1.0"
    manifest_version: str = "v1"

    generation_id: uuid.UUID = Field(description="Unique UUID of this physical index generation")
    candidate_id: uuid.UUID = Field(description="UUID of the candidate")
    profile_version: str = Field(min_length=1, description="Exact profile snapshot version")
    purpose: str = Field(min_length=1, description="Inclusion purpose applied")
    snapshot_fingerprint: str = Field(
        min_length=1, description="SHA-256 fingerprint of approved profile snapshot"
    )
    chunk_manifest_hash: str = Field(
        min_length=1, description="SHA-256 manifest fingerprint from upstream ChunkSet"
    )
    inclusion_rule_version: str = Field(default="v1", min_length=1)
    chunking_version: str = Field(default="v1", min_length=1)

    embedding_configuration: EmbeddingConfiguration = Field(
        description="Measured embedding configuration used for this build"
    )
    embedding_space_fingerprint: str = Field(
        min_length=1, description="Canonical SHA-256 fingerprint of the embedding space"
    )
    index_settings: IndexSettings = Field(description="Effective index settings applied")
    settings_fingerprint: str = Field(
        min_length=1, description="Canonical SHA-256 fingerprint of index settings"
    )

    row_count: int = Field(ge=0, description="Total number of indexed evidence chunks / rows")
    dimension: int = Field(gt=0, description="Vector embedding dimension")
    rows: list[IndexRowMapping] = Field(
        default_factory=list,
        description="Deterministic ordered row mappings",
    )
    payload_files: dict[str, PayloadFileInfo] = Field(
        default_factory=dict,
        description="Physical payload files (vectors, keywords, chunks) and their digests",
    )

    logical_build_fingerprint: str = Field(
        min_length=1,
        description="Deterministic SHA-256 of semantic inputs and configurations",
    )
    artifact_fingerprint: str = Field(
        min_length=1,
        description="SHA-256 digest covering logical build fingerprint and payload file hashes",
    )
    created_at: UtcDatetime = Field(description="Timestamp when the manifest was finalized")


class IndexBuildRequest(ContractModel):
    """Explicit bound request to construct a local vector and keyword index."""

    schema_version: str = "1.0"
    candidate_id: uuid.UUID = Field(description="UUID of the candidate")
    profile_version: str = Field(min_length=1, description="Target profile snapshot version")
    purpose: str = Field(min_length=1, description="Target inclusion purpose")
    chunk_set: ChunkSet = Field(description="Complete validated CONTEXT-02 chunk set")
    embedding_config: EmbeddingConfiguration = Field(
        description="Measured embedding model configuration"
    )
    settings: IndexSettings = Field(default_factory=IndexSettings, description="Index settings")
    build_mode: Literal["full_rebuild", "incremental"] = Field(
        default="full_rebuild",
        description="Build mode: full_rebuild (default and required for v1)",
    )
    expected_prior_token: str | None = Field(
        default=None,
        description="Optional expected prior activation token for compare-and-swap activation",
    )
    change_set: ChunkChangeSet | None = Field(
        default=None,
        description="Optional change set provided as an advisory hint",
    )

    @model_validator(mode="after")
    def _validate_chunk_set_alignment(self) -> IndexBuildRequest:
        if self.candidate_id != self.chunk_set.candidate_id:
            raise ValueError(
                f"Candidate mismatch: request candidate {self.candidate_id} != chunk_set candidate {self.chunk_set.candidate_id}"
            )
        if self.profile_version != self.chunk_set.profile_version:
            raise ValueError(
                f"Profile version mismatch: request profile {self.profile_version} != chunk_set profile {self.chunk_set.profile_version}"
            )
        if self.purpose != self.chunk_set.purpose:
            raise ValueError(
                f"Purpose mismatch: request purpose {self.purpose} != chunk_set purpose {self.chunk_set.purpose}"
            )
        return self


class IndexBuildRecord(ContractModel):
    """Durable ledger record documenting the execution of an index build."""

    schema_version: str = "1.0"
    build_id: uuid.UUID = Field(description="Unique UUID for this build attempt")
    generation_id: uuid.UUID = Field(description="UUID of the generation built (or attempted)")
    candidate_id: uuid.UUID = Field(description="UUID of the candidate")
    profile_version: str = Field(min_length=1, description="Profile version")
    purpose: str = Field(min_length=1, description="Purpose")
    status: Literal["completed", "failed"] = Field(description="Build execution status")
    started_at: UtcDatetime = Field(description="UTC start time of build")
    completed_at: UtcDatetime = Field(description="UTC completion time of build")
    duration_ms: float = Field(ge=0.0, description="Total build duration in milliseconds")

    chunk_count: int = Field(ge=0, description="Total chunks processed")
    vector_count: int = Field(ge=0, description="Total vectors generated")
    term_count: int = Field(ge=0, description="Total distinct keyword terms indexed")
    embedding_call_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Audit call IDs from ModelProvider embedding calls",
    )
    total_input_bytes: int = Field(ge=0, description="Total raw text bytes embedded")
    payload_bytes: int = Field(ge=0, description="Total on-disk payload bytes written")
    observed_memory_bytes: int | None = Field(
        default=None, ge=0, description="Peak observed memory during build if measured"
    )

    logical_build_fingerprint: str = Field(
        min_length=1, description="Logical build fingerprint of inputs"
    )
    artifact_fingerprint: str | None = Field(
        default=None, description="Artifact fingerprint if completed"
    )
    error: ClassifiedError | None = Field(
        default=None, description="Classified error if build failed"
    )
    is_verified: bool = Field(default=True, description="True if payload hashes verified on disk")


class IndexBuildResult(ContractModel):
    """Successful outcome of an index build."""

    schema_version: str = "1.0"
    generation_id: uuid.UUID = Field(description="UUID of the built generation")
    manifest: IndexManifest = Field(description="Manifest of the created generation")
    build_record: IndexBuildRecord = Field(description="Ledger build record")
    activation_token: str = Field(
        min_length=1, description="Token generated for atomic activation"
    )


class IndexReadRequest(ContractModel):
    """Consumer authorization and expected-binding request for index access."""

    schema_version: str = "1.0"
    candidate_id: uuid.UUID = Field(description="UUID of the candidate")
    purpose: str = Field(min_length=1, description="Purpose (assessment, cv, cover_letter)")
    expected_profile_version: str | None = Field(
        default=None,
        description="Expected profile version; required for current_use validation",
    )
    expected_snapshot_fingerprint: str | None = Field(
        default=None,
        description="Expected profile snapshot fingerprint",
    )
    expected_chunk_manifest_hash: str | None = Field(
        default=None,
        description="Expected chunk manifest fingerprint",
    )
    expected_embedding_space_fingerprint: str | None = Field(
        default=None,
        description="Expected embedding space fingerprint",
    )
    expected_settings_fingerprint: str | None = Field(
        default=None,
        description="Expected index settings fingerprint",
    )
    authorization_mode: Literal["current_use", "frozen_use"] = Field(
        default="current_use",
        description="current_use validates against active pointer; frozen_use requires frozen_generation_id",
    )
    frozen_generation_id: uuid.UUID | None = Field(
        default=None,
        description="Explicitly authorized frozen generation ID if authorization_mode is frozen_use",
    )


class TermPosting(ContractModel):
    """Keyword posting linking a search term to an evidence chunk row."""

    schema_version: str = "1.0"
    term: str = Field(min_length=1, description="Normalized search term")
    row_ordinal: int = Field(ge=0, description="0-based row ordinal of the containing chunk")
    term_frequency: int = Field(ge=1, description="Frequency of term in this chunk")
    positions: list[int] = Field(
        default_factory=list,
        description="0-based token positions within the chunk's retrieval text",
    )


class IndexPin(ContractModel):
    """Pin record preventing cleanup of a retired index generation while in active use."""

    schema_version: str = "1.0"
    pin_id: uuid.UUID = Field(description="Unique UUID for this pin")
    generation_id: uuid.UUID = Field(description="UUID of the pinned generation")
    pinned_for: str = Field(min_length=1, description="Reason / consumer type (e.g. reader, generation_request)")
    pinned_by: str = Field(min_length=1, description="Identifier of the pinning caller / worker")
    created_at: UtcDatetime = Field(description="UTC timestamp when pin was created")
    released_at: UtcDatetime | None = Field(
        default=None, description="UTC timestamp when pin was released"
    )

