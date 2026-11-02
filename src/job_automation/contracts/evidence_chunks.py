"""Evidence chunk contracts for CONTEXT-02.

Defines deterministic, versioned evidence chunking contracts:
- ChunkingSettings: Granularity, size guards, versions, and parent policy.
- AncestorContext: Structured permitted ancestor anchors.
- ChunkSourceMapping: Field-level traceability to C08 approved candidate facts.
- EvidenceChunk: Whole-fact chunk with stable identity, content version, and exact binding.
- ChunkSet: Complete manifest of chunks for an approved snapshot and purpose.
- BindingTransition / ChunkChangeSet: Invalidation report between base and target manifests.
- ChunkBuildRequest: Explicit bound request for offline chunk creation.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence import CandidateEvidenceReference, SourceSpan
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import ProfileSnapshot


class ChunkingSettings(ContractModel):
    """Configuration and versioning for evidence chunk construction."""

    schema_version: str = "1.0"
    algorithm_version: str = "v1"
    identity_scheme_version: str = "v1"
    rendering_version: str = "v1"
    parent_policy_version: str = "v1"
    granularity: Literal["whole_fact"] = "whole_fact"
    max_chunk_chars: int | None = Field(
        default=None,
        gt=0,
        description="Optional maximum character size guard for retrieval_text",
    )
    strict_parents: bool = Field(
        default=False,
        description="If True, missing or restricted parents raise permission error",
    )
    size_unit: str = Field(
        default="chars",
        description="Unit of measurement for chunk size guards",
    )
    overflow_behavior: str = Field(
        default="error",
        description="Behavior on size guard overflow: 'error'",
    )

    @field_validator("granularity")
    @classmethod
    def _validate_granularity(cls, v: str) -> str:
        if v != "whole_fact":
            raise ValueError(f"Unsupported granularity '{v}'. Only 'whole_fact' is supported in v1.")
        return v

    @field_validator("overflow_behavior")
    @classmethod
    def _validate_overflow_behavior(cls, v: str) -> str:
        if v != "error":
            raise ValueError(f"Unsupported overflow_behavior '{v}'. Only 'error' is supported.")
        return v


class AncestorContext(ContractModel):
    """Structured permitted ancestor anchor attached to child evidence."""

    schema_version: str = "1.0"
    fact_id: uuid.UUID = Field(description="UUID of the ancestor fact")
    kind: EvidenceFactKind = Field(description="Evidence kind of the ancestor")
    title: str = Field(min_length=1, description="Headline or title of the ancestor fact")
    organization: str | None = Field(
        default=None,
        description="Employer, client, or institution organization",
    )
    start_date: PrecisionDate | None = Field(
        default=None,
        description="Start date with explicit precision",
    )
    end_date: PrecisionDate | None = Field(
        default=None,
        description="End date with explicit precision",
    )
    parent_id: uuid.UUID | None = Field(
        default=None,
        description="Parent UUID of this ancestor if part of a deeper hierarchy",
    )
    provenance: str = Field(
        default="unspecified",
        min_length=1,
        description="Exact approved provenance string from C01",
    )
    allowed_uses: list[str] = Field(
        default_factory=list,
        description="Approved allowed uses of this ancestor fact",
    )


class ChunkSourceMapping(ContractModel):
    """Fine-grained mapping linking a chunk assertion back to an approved C01 field."""

    schema_version: str = "1.0"
    reference: CandidateEvidenceReference = Field(
        description="C08 candidate reference (profile_version, fact_id)",
    )
    field_path: str = Field(
        min_length=1,
        description="Field path in source fact (e.g. 'title', 'claims[0]', 'skills[2]')",
    )
    list_index: int | None = Field(
        default=None,
        ge=0,
        description="0-based list index for claims, skills, or metrics",
    )
    exact_value: str | None = Field(
        default=None,
        description="Exact string value from the approved source field",
    )
    char_span: SourceSpan | None = Field(
        default=None,
        description="Optional character span within the field",
    )
    is_ancestor_context: bool = Field(
        default=False,
        description="True if this mapping cites ancestor context rather than primary evidence",
    )


class EvidenceChunk(ContractModel):
    """Deterministic, versioned evidence chunk representing one primary fact."""

    schema_version: str = "1.0"
    chunk_id: uuid.UUID = Field(
        description="Stable UUIDv5 derived from candidate_id, purpose, fact_id, slot",
    )
    chunk_version: str = Field(
        min_length=1,
        description="SHA-256 content fingerprint over normalized projection",
    )
    candidate_id: uuid.UUID = Field(description="UUID of the candidate")
    profile_version: str = Field(min_length=1, description="Exact C01 profile version cited")
    purpose: str = Field(min_length=1, description="Inclusion purpose applied")
    primary_fact_id: uuid.UUID = Field(description="UUID of the primary CandidateFact")
    primary_kind: EvidenceFactKind = Field(description="Kind of the primary fact")
    parent_id: uuid.UUID | None = Field(
        default=None,
        description="Original direct parent ID if hierarchical",
    )
    ancestor_context: list[AncestorContext] = Field(
        default_factory=list,
        description="Ordered permitted ancestor anchors",
    )
    title: str = Field(min_length=1, description="Primary headline / title")
    organization: str | None = Field(
        default=None,
        description="Primary employer or institution",
    )
    start_date: PrecisionDate | None = Field(
        default=None,
        description="Primary start date",
    )
    end_date: PrecisionDate | None = Field(
        default=None,
        description="Primary end date",
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Demonstrated skills attached to this primary fact",
    )
    claims: list[str] = Field(
        default_factory=list,
        description="Specific factual claims / accomplishments",
    )
    metrics: list[str] = Field(
        default_factory=list,
        description="Verified quantitative metrics",
    )
    provenance: str = Field(
        default="unspecified",
        min_length=1,
        description="Exact approved provenance string from primary fact",
    )
    primary_allowed_uses: list[str] = Field(
        default_factory=list,
        description="Allowed uses declared on the primary fact",
    )
    effective_allowed_uses: list[str] = Field(
        default_factory=list,
        description="Intersection of allowed uses across primary and included ancestors",
    )
    sources: list[ChunkSourceMapping] = Field(
        default_factory=list,
        description="Complete field-level source mappings to approved snapshot",
    )
    retrieval_text: str = Field(
        min_length=1,
        description="Deterministic formatted text for retrieval and model consumption",
    )
    dependency_fingerprints: dict[str, str] = Field(
        default_factory=dict,
        description="SHA-256 fingerprint for each contributing fact (primary and ancestors)",
    )
    contextual_limitations: list[str] = Field(
        default_factory=list,
        description="Explicit limitations (e.g. omitted restricted parent references)",
    )
    binding_fingerprint: str = Field(
        min_length=1,
        description="SHA-256 fingerprint binding chunk to exact snapshot and C08 citations",
    )


class ChunkSet(ContractModel):
    """Complete manifest of evidence chunks for an approved snapshot and purpose."""

    schema_version: str = "1.0"
    candidate_id: uuid.UUID = Field(description="UUID of the candidate")
    profile_version: str = Field(min_length=1, description="Exact profile snapshot version")
    purpose: str = Field(min_length=1, description="Inclusion purpose applied")
    snapshot_fingerprint: str = Field(
        min_length=1,
        description="SHA-256 digest of the approved profile snapshot",
    )
    inclusion_rule_version: str = Field(default="v1", min_length=1)
    chunking_version: str = Field(default="v1", min_length=1)
    settings_fingerprint: str = Field(
        min_length=1,
        description="SHA-256 digest of effective chunking settings",
    )
    chunks: list[EvidenceChunk] = Field(
        default_factory=list,
        description="Ordered list of evidence chunks",
    )
    eligible_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="All eligible fact UUIDs in deterministic order",
    )
    coverage_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Fact UUIDs covered by chunks",
    )
    excluded_fact_count: int = Field(
        default=0,
        ge=0,
        description="Count of facts excluded by purpose permissions",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Deterministic inclusion and chunking warnings",
    )
    manifest_fingerprint: str = Field(
        min_length=1,
        description="SHA-256 digest over the complete manifest binding",
    )

    @model_validator(mode="after")
    def _validate_manifest_consistency(self) -> ChunkSet:
        chunk_primary_ids = [c.primary_fact_id for c in self.chunks]
        if set(chunk_primary_ids) != set(self.coverage_fact_ids):
            raise ValueError(
                f"Coverage IDs ({len(self.coverage_fact_ids)}) do not match primary fact IDs in chunks ({len(chunk_primary_ids)})"
            )
        if set(self.coverage_fact_ids) != set(self.eligible_fact_ids):
            raise ValueError(
                f"Coverage IDs ({len(self.coverage_fact_ids)}) do not match eligible fact IDs ({len(self.eligible_fact_ids)})"
            )
        return self


class BindingTransition(ContractModel):
    """Record of binding state change for an individual chunk identity."""

    schema_version: str = "1.0"
    chunk_id: uuid.UUID = Field(description="UUID of the affected chunk")
    old_binding: str | None = Field(
        default=None,
        description="Old binding fingerprint if present in base manifest",
    )
    new_binding: str | None = Field(
        default=None,
        description="New binding fingerprint if present in target manifest",
    )
    reason_code: str = Field(
        min_length=1,
        description="Code: 'added', 'removed_tombstone', 'content_updated', 'rebound_snapshot'",
    )


class ChunkChangeSet(ContractModel):
    """Detailed invalidation and diff report between base and target chunk sets."""

    schema_version: str = "1.0"
    candidate_id: uuid.UUID = Field(description="UUID of the candidate")
    purpose: str = Field(min_length=1, description="Inclusion purpose applied")
    base_manifest_fingerprint: str | None = Field(
        default=None,
        description="Manifest fingerprint of base ChunkSet, or None for initial build",
    )
    target_manifest_fingerprint: str = Field(
        min_length=1,
        description="Manifest fingerprint of target ChunkSet",
    )
    added_chunk_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Chunk IDs present in target but not in base",
    )
    removed_chunk_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Chunk IDs present in base but absent from target (tombstones)",
    )
    content_changed_chunk_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Chunk IDs present in both with changed content version",
    )
    rebound_unchanged_chunk_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Chunk IDs present in both with identical content version but new binding",
    )
    binding_transitions: list[BindingTransition] = Field(
        default_factory=list,
        description="Per-chunk transition descriptors",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Summary diagnostic reason strings",
    )
    replacement_required: bool = Field(
        default=False,
        description="True if downstream index requires mutation/replacement",
    )


class ChunkBuildRequest(ContractModel):
    """Explicit, fully bound request for constructing a ChunkSet."""

    schema_version: str = "1.0"
    snapshot: ProfileSnapshot = Field(
        description="Approved C01 candidate profile snapshot",
    )
    purpose: str = Field(
        min_length=1,
        description="Target purpose: 'assessment', 'cv', or 'cover_letter'",
    )
    settings: ChunkingSettings = Field(
        default_factory=ChunkingSettings,
        description="Versioned chunking settings",
    )
    explicit_required_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Caller-specified mandatory fact UUIDs",
    )

