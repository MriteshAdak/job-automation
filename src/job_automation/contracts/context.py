"""C09 ContextBundle contracts.

Represents constructed candidate context for assessment or generation:
full JSON or RAG retrieved facts, with mandatory eligibility facts and budget accounting.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import ContextStrategy, EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateEligibility, CandidateFact


class ChronologyReference(ContractModel):
    """Reference to an essential chronology anchor fact with preserved dates and versions."""

    profile_version: str = Field(min_length=1, description="Profile version containing the fact")
    fact_id: uuid.UUID = Field(description="UUID of the chronology fact")
    kind: EvidenceFactKind = Field(description="Kind of evidence fact (employment, education, etc.)")
    title: str = Field(min_length=1, description="Title of the anchor fact")
    start_date: PrecisionDate | None = Field(default=None, description="Start date with preserved precision")
    end_date: PrecisionDate | None = Field(default=None, description="End date with preserved precision")
    reason: str = Field(min_length=1, description="Reason for inclusion as chronology anchor")


class MandatoryFactReason(ContractModel):
    """Reason code documenting why a fact is designated as mandatory context."""

    fact_id: uuid.UUID = Field(description="UUID of the mandatory fact")
    reason: str = Field(min_length=1, description="Reason code for mandatory status")


class StructuredMandatoryContext(ContractModel):
    """Authoritative structured representation of mandatory eligibility and chronology facts."""

    mandatory_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Ordered unique UUIDs of mandatory facts",
    )
    fact_reasons: list[MandatoryFactReason] = Field(
        default_factory=list,
        description="Reason codes for each mandatory fact",
    )
    chronology: list[ChronologyReference] = Field(
        default_factory=list,
        description="Chronology references preserving precision dates and versions",
    )
    explicit_eligibility: CandidateEligibility = Field(
        description="Explicit candidate eligibility from approved C01 snapshot",
    )
    eligibility_source: str = Field(
        min_length=1,
        description="Provenance citation for eligibility fields (e.g. 'v1#explicit_eligibility')",
    )


class BudgetReport(ContractModel):
    """Comprehensive token budget accounting across the entire rendered prompt."""

    total_input_tokens: int = Field(ge=0, description="Total tokens consumed by complete rendered input P")
    candidate_tokens: int = Field(ge=0, description="Tokens consumed by candidate context model projection")
    instruction_tokens: int = Field(ge=0, description="Tokens consumed by instructions and system prompt")
    job_tokens: int = Field(ge=0, description="Tokens consumed by job posting description and requirements")
    framing_tokens: int = Field(ge=0, description="Tokens consumed by chat framing, headers, and separators")
    output_reserve: int = Field(ge=0, description="Tokens reserved for model completion output O")
    safety_allowance: int = Field(ge=0, description="Safety allowance margin M")
    effective_window: int = Field(gt=0, description="Effective model context window limit L")
    candidate_allowance: int = Field(description="Allocated candidate context allowance")
    total_demand: int = Field(ge=0, description="Total budget demand P + O + M")
    remaining_capacity: int = Field(description="Remaining capacity in tokens L - (P + O + M)")
    overflow: int = Field(ge=0, description="Overflow excess if total_demand exceeds effective_window")
    fits: bool = Field(description="True if total_demand <= effective_window")
    measurement_method: str = Field(min_length=1, description="Identifier of the tokenizer or estimator used")
    measurement_version: str = Field(min_length=1, description="Version of the tokenizer or estimator")
    is_exact: bool = Field(description="True if measured with an exact tokenizer; False if estimated")


class ContextBundle(ContractModel):
    """C09 Context Bundle.

    Snapshot of selected candidate evidence facts and mandatory context
    for downstream LLM assessment or document generation.
    """

    strategy: ContextStrategy = Field(
        description="Context strategy used: json (full snapshot) or rag (retrieved chunks)"
    )
    profile_version: str = Field(min_length=1, description="Version of the candidate profile snapshot")
    posting_revision: str = Field(min_length=1, description="Job posting revision or content hash")
    ordered_facts: list[CandidateFact] = Field(
        default_factory=list,
        description="Ordered candidate facts included in this context",
    )
    mandatory_context: list[str] = Field(
        default_factory=list,
        description="Mandatory eligibility/chronology facts that bypass top-k retrieval",
    )
    selected_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="UUIDs of facts selected for this bundle",
    )
    query_version: str | None = Field(
        default=None,
        description="Version of the requirement query used for retrieval (RAG only)",
    )
    index_version: str | None = Field(
        default=None,
        description="Version/digest of the embedding index used (RAG only)",
    )
    retrieval_settings: dict[str, Any] | None = Field(
        default=None,
        description="Retrieval settings (e.g. top_k, similarity_threshold) if RAG",
    )
    token_budget: int = Field(gt=0, description="Allocated token budget for context")
    estimated_tokens: int = Field(ge=0, description="Estimated token count of this context bundle")
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings regarding budget pressure or omitted non-mandatory items",
    )

    # Rich typed metadata for CONTEXT-01 full-profile JSON and future RAG
    candidate_id: uuid.UUID | None = Field(
        default=None,
        description="Stable UUID of the candidate",
    )
    purpose: str | None = Field(
        default=None,
        description="Purpose for which this context was constructed (assessment, cv, cover_letter)",
    )
    inclusion_rule_version: str | None = Field(
        default=None,
        description="Version of inclusion rules applied",
    )
    mandatory_policy_version: str | None = Field(
        default=None,
        description="Version of mandatory context policy applied",
    )
    builder_version: str | None = Field(
        default=None,
        description="Version of the context builder used",
    )
    serialization_version: str | None = Field(
        default=None,
        description="Version of the serialization format used",
    )
    mandatory_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="UUIDs of mandatory facts included in this bundle",
    )
    structured_mandatory: StructuredMandatoryContext | None = Field(
        default=None,
        description="Structured mandatory eligibility and chronology context",
    )
    content_fingerprint: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of the complete rendered input context",
    )
    budget_report: BudgetReport | None = Field(
        default=None,
        description="Comprehensive whole-prompt token budget report",
    )
    retrieval_audit: dict[str, Any] | None = Field(
        default=None,
        description="Auxiliary audit trace of retrieval and fusion (RAG only)",
    )

