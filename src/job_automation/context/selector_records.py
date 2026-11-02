"""Domain records and request/result contracts for CONTEXT-04 context selector."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field, model_validator

from job_automation.context.records import JsonContextRequest, RenderedPrompt
from job_automation.context.retrieval_settings import (
    DEFAULT_RETRIEVAL_SETTINGS,
    RetrievalSettings,
)
from job_automation.contracts.base import ContractModel
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexReadRequest,
)


class RequirementQuery(ContractModel):
    """Normalized query generated from a requirement or job section."""

    query_id: str = Field(min_length=1, description="Stable query identifier (e.g. 'q_0')")
    original_text: str = Field(min_length=1, description="Original requirement string")
    query_text: str = Field(min_length=1, description="Normalized query text")
    terms: list[str] = Field(default_factory=list, description="Extracted search terms")
    source_span: str | None = Field(default=None, description="Optional span or citation")
    provenance: str | None = Field(default=None, description="Origin indicator (e.g. 'requirement', 'job_fallback')")


class RequirementQuerySet(ContractModel):
    """Deterministic collection of requirement queries with content fingerprint."""

    recipe_version: str = Field(default="v1", description="Query recipe version")
    queries: list[RequirementQuery] = Field(default_factory=list, description="Ordered requirement queries")
    query_set_fingerprint: str = Field(min_length=1, description="SHA-256 fingerprint of all queries")


class RetrievalHit(ContractModel):
    """Single channel retrieval match for an evidence chunk."""

    chunk_id: uuid.UUID = Field(description="UUID of the matched evidence chunk")
    fact_id: uuid.UUID = Field(description="UUID of the underlying primary candidate fact")
    channel: Literal["keyword", "semantic"] = Field(description="Retrieval channel producing this hit")
    score: float = Field(description="Channel score (term count or cosine similarity)")
    rank: int = Field(ge=1, description="1-based channel rank for this query")
    query_id: str = Field(min_length=1, description="Query ID that produced this hit")


class FusedCandidate(ContractModel):
    """Candidate primary fact with fused reciprocal rank score across channels and queries."""

    fact_id: uuid.UUID = Field(description="UUID of candidate primary fact")
    fused_score: float = Field(ge=0.0, description="Reciprocal Rank Fusion score")
    channel_hits: list[RetrievalHit] = Field(default_factory=list, description="Hits contributing to this candidate")
    query_count: int = Field(default=1, ge=1, description="Number of queries that retrieved this fact")
    best_channel_rank: int = Field(default=1, ge=1, description="Best rank achieved in any channel")
    selection_reason: str = Field(default="fused_score", description="Reason code for candidate selection")
    is_admitted: bool = Field(default=False, description="True if fact was admitted into prompt budget")
    omission_reason: str | None = Field(default=None, description="Reason if omitted (e.g. 'budget_omitted')")


class RetrievalTrace(ContractModel):
    """Comprehensive, safe diagnostic trace of retrieval, fusion, and packing decisions."""

    query_version: str = Field(min_length=1, description="Query set recipe and fingerprint")
    index_version: str = Field(min_length=1, description="Index generation identifier or manifest hash")
    channel_statuses: dict[str, str] = Field(default_factory=dict, description="Channel execution statuses")
    retrieved_hits: list[RetrievalHit] = Field(default_factory=list, description="All raw channel hits")
    fused_candidates: list[FusedCandidate] = Field(default_factory=list, description="Fused candidate ranking")
    selected_fact_ids: list[uuid.UUID] = Field(default_factory=list, description="Fact UUIDs admitted into bundle")
    retrieved_fact_ids: list[uuid.UUID] = Field(default_factory=list, description="All retrieved fact UUIDs")
    mandatory_fact_ids: list[uuid.UUID] = Field(default_factory=list, description="Mandatory fact UUIDs bypassing retrieval")
    budget_omitted_fact_ids: list[uuid.UUID] = Field(default_factory=list, description="Candidate fact UUIDs omitted due to budget")
    warnings: list[str] = Field(default_factory=list, description="Safe warning codes")


class ContextSelectionRequest(ContractModel):
    """Explicit, fully bound request for selecting candidate context (JSON or RAG)."""

    strategy: ContextStrategy = Field(description="Strategy: ContextStrategy.JSON or ContextStrategy.RAG")
    snapshot: ProfileSnapshot = Field(description="Approved candidate profile snapshot")
    purpose: str = Field(min_length=1, description="Context purpose ('assessment', 'cv', 'cover_letter')")
    canonical_job_id: uuid.UUID = Field(description="Stable UUID of the target canonical job")
    posting_revision: str = Field(min_length=1, description="Exact posting revision identifier")
    job_content: NormalizedPosting = Field(description="Normalized job posting content")
    requirements: list[str] = Field(default_factory=list, description="Caller-provided requirements")
    instruction_text: str = Field(default="", description="System/developer prompt instructions")
    output_schema_text: str | None = Field(default=None, description="Structured output schema instructions")
    model_identifier: str = Field(min_length=1, description="Target model identifier")
    context_limit: int = Field(gt=0, description="Effective model context window limit L")
    output_reserve: int = Field(default=512, ge=0, description="Reserved completion tokens O")
    safety_allowance: int = Field(default=64, ge=0, description="Safety allowance tokens M")
    mandatory_policy_version: str = Field(default="v1", description="Mandatory context policy version")
    inclusion_rule_version: str = Field(default="v1", description="Inclusion rule version")
    builder_version: str = Field(default="v1", description="Builder version")
    serialization_version: str = Field(default="v1", description="Serialization format version")
    explicit_mandatory_fact_ids: list[uuid.UUID] = Field(default_factory=list, description="Explicit mandatory facts")
    template_name: str | None = Field(default=None, description="Prompt template identifier")
    chat_template_version: str | None = Field(default=None, description="Chat template framing version")
    require_exact_measurement: bool = Field(default=False, description="Require exact tokenizer measurement")
    settings_fingerprint: str | None = Field(default=None, description="Settings fingerprint")

    # RAG specific settings
    retrieval_settings: RetrievalSettings | None = Field(
        default=None,
        description="Retrieval settings for RAG; defaults to DEFAULT_RETRIEVAL_SETTINGS if strategy is RAG",
    )
    index_read_request: IndexReadRequest | None = Field(
        default=None,
        description="Consumer authorization request for index access",
    )
    embedding_config: EmbeddingConfiguration | None = Field(
        default=None,
        description="Bound embedding configuration for query embeddings",
    )

    @model_validator(mode="before")
    @classmethod
    def populate_defaults_and_validate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            strat = data.get("strategy")
            if (strat == ContextStrategy.RAG or strat == "rag") and data.get("retrieval_settings") is None:
                data = dict(data)
                data["retrieval_settings"] = DEFAULT_RETRIEVAL_SETTINGS
        return data

    def to_json_context_request(self) -> JsonContextRequest:
        """Project to JsonContextRequest for CONTEXT-01 delegation."""
        return JsonContextRequest(
            snapshot=self.snapshot,
            purpose=self.purpose,
            canonical_job_id=self.canonical_job_id,
            posting_revision=self.posting_revision,
            job_content=self.job_content,
            requirements=list(self.requirements),
            instruction_text=self.instruction_text,
            output_schema_text=self.output_schema_text,
            model_identifier=self.model_identifier,
            context_limit=self.context_limit,
            output_reserve=self.output_reserve,
            safety_allowance=self.safety_allowance,
            mandatory_policy_version=self.mandatory_policy_version,
            inclusion_rule_version=self.inclusion_rule_version,
            builder_version=self.builder_version,
            serialization_version=self.serialization_version,
            explicit_mandatory_fact_ids=list(self.explicit_mandatory_fact_ids),
            template_name=self.template_name,
            chat_template_version=self.chat_template_version,
            require_exact_measurement=self.require_exact_measurement,
            settings_fingerprint=self.settings_fingerprint,
        )


class ContextSelectionResult(ContractModel):
    """Result envelope containing C09 bundle, rendered prompt, and auxiliary retrieval trace."""

    bundle: ContextBundle = Field(description="Admitted C09 ContextBundle")
    rendered_prompt: RenderedPrompt = Field(description="Frozen rendered prompt payload used for measurement")
    trace: RetrievalTrace | None = Field(default=None, description="Auxiliary retrieval trace (RAG only)")
    construction_fingerprint: str = Field(min_length=1, description="SHA-256 fingerprint binding complete selection")
