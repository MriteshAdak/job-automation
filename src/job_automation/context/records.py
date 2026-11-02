"""Domain records and request contracts for CONTEXT-01 full-profile JSON context.

Provides:
- JsonContextRequest: Versioned, fully bound request for JSON context bundle generation.
- PreparedProfileContext: Shared purpose-filtered evidence universe and mandatory context representation.
- RenderedPrompt: Complete rendered prompt components including framing and candidate projection.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.context import ChronologyReference
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileSnapshot,
)


class JsonContextRequest(ContractModel):
    """Explicit, fully bound request for constructing a full JSON ContextBundle.

    Binds approved candidate profile snapshot, exact job revision and content,
    purpose, instructions, schema requirements, and explicit model window/reserve constraints.
    """

    snapshot: ProfileSnapshot = Field(
        description="Approved C01 candidate profile snapshot",
    )
    purpose: str = Field(
        min_length=1,
        description="Purpose for context construction ('assessment', 'cv', or 'cover_letter')",
    )
    canonical_job_id: uuid.UUID = Field(
        description="Stable UUID of the target canonical job",
    )
    posting_revision: str = Field(
        min_length=1,
        description="Exact posting revision identifier or content hash",
    )
    job_content: NormalizedPosting = Field(
        description="Normalized C06 job posting content corresponding to posting_revision",
    )
    requirements: list[str] = Field(
        default_factory=list,
        description="Caller-prepared job requirements or evaluation queries",
    )
    instruction_text: str = Field(
        default="",
        description="System or developer instructions to be rendered in the prompt",
    )
    output_schema_text: str | None = Field(
        default=None,
        description="Structured output schema instructions if applicable",
    )
    model_identifier: str = Field(
        min_length=1,
        description="Target model identifier (e.g. 'llama3:8b-instruct-q4_K_M')",
    )
    context_limit: int = Field(
        gt=0,
        description="Effective model context window capacity L in tokens",
    )
    output_reserve: int = Field(
        default=512,
        ge=0,
        description="Tokens reserved for model completion output O",
    )
    safety_allowance: int = Field(
        default=64,
        ge=0,
        description="Safety allowance margin M for tokenization variations",
    )
    mandatory_policy_version: str = Field(
        default="v1",
        description="Version identifier of the mandatory context policy",
    )
    inclusion_rule_version: str = Field(
        default="v1",
        description="Version identifier of the inclusion rules applied",
    )
    builder_version: str = Field(
        default="v1",
        description="Version identifier of the JSON context builder",
    )
    serialization_version: str = Field(
        default="v1",
        description="Version identifier of the candidate JSON serialization format",
    )
    explicit_mandatory_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Caller-specified mandatory fact UUIDs to include in mandatory context",
    )
    template_name: str | None = Field(
        default=None,
        description="Prompt or chat template identifier",
    )
    chat_template_version: str | None = Field(
        default=None,
        description="Version identifier of chat template framing",
    )
    require_exact_measurement: bool = Field(
        default=False,
        description="If True, rejects heuristic estimates and requires exact tokenizer measurement",
    )
    settings_fingerprint: str | None = Field(
        default=None,
        description="Optional content hash of effective settings",
    )


class PreparedProfileContext(ContractModel):
    """Shared purpose-aware profile context preparation result.

    Guarantees:
    - Identical universe of eligible facts for both JSON and future RAG strategies.
    - Authoritative mandatory fact set derived from chronology anchors and ancestor chains.
    - Faithful copy of explicit candidate eligibility without fabricated proficiencies.
    - Deeply detached collections preventing mutation of underlying snapshot.
    """

    candidate_id: uuid.UUID = Field(description="Stable UUID of the candidate")
    profile_version: str = Field(min_length=1, description="Version of the candidate profile snapshot")
    purpose: str = Field(min_length=1, description="Inclusion purpose applied")
    inclusion_rule_version: str = Field(default="v1", description="Inclusion rule version used")
    mandatory_policy_version: str = Field(default="v1", description="Mandatory policy version used")
    eligible_facts: list[CandidateFact] = Field(
        default_factory=list,
        description="Complete ordered list of permitted CandidateFact records",
    )
    eligible_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="UUIDs of eligible facts in deterministic order",
    )
    mandatory_facts: list[CandidateFact] = Field(
        default_factory=list,
        description="Ordered list of mandatory facts",
    )
    mandatory_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Unique ordered UUIDs of mandatory facts",
    )
    mandatory_reasons: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Reason codes keyed by fact_id string",
    )
    chronology: list[ChronologyReference] = Field(
        default_factory=list,
        description="Chronology references preserving precision dates and versions",
    )
    explicit_eligibility: CandidateEligibility = Field(
        description="Faithfully copied explicit eligibility from approved snapshot",
    )
    eligibility_source: str = Field(
        min_length=1,
        description="Provenance citation for explicit eligibility",
    )
    excluded_fact_count: int = Field(ge=0, description="Count of facts excluded by purpose permissions")
    warnings: list[str] = Field(
        default_factory=list,
        description="Deterministic warnings regarding restricted parents or conflicts",
    )


class RenderedPrompt(ContractModel):
    """Structured components of the complete rendered prompt for token measurement."""

    full_prompt: str = Field(description="Complete rendered prompt string including all framing and data")
    instruction_text: str = Field(default="", description="Rendered system and developer instructions")
    job_text: str = Field(description="Rendered job posting text and metadata")
    requirements_text: str = Field(default="", description="Rendered caller-prepared requirements")
    output_schema_text: str = Field(default="", description="Rendered output schema instructions")
    candidate_json: str = Field(description="Rendered canonical candidate model projection JSON")
    framing_text: str = Field(default="", description="Framing delimiters, headers, and separators")
    render_template_version: str = Field(default="v1", description="Version of prompt rendering template")


class MeasurementResult(ContractModel):
    """Result of measuring a single text component."""

    token_count: int = Field(ge=0, description="Measured or estimated token count")
    is_exact: bool = Field(description="True if measured using an exact tokenizer")
    method: str = Field(min_length=1, description="Measurement method identifier")
    version: str = Field(min_length=1, description="Measurement method version")


class WholePromptMeasurement(ContractModel):
    """Whole-prompt token measurement with individual component breakdown."""

    total_input_tokens: int = Field(ge=0, description="Total tokens in complete rendered prompt P")
    candidate_tokens: int = Field(ge=0, description="Tokens in candidate model projection JSON")
    instruction_tokens: int = Field(ge=0, description="Tokens in instructions")
    job_tokens: int = Field(ge=0, description="Tokens in job posting text and requirements")
    framing_tokens: int = Field(ge=0, description="Tokens in prompt framing headers and separators")
    is_exact: bool = Field(description="True if measured using an exact tokenizer")
    method: str = Field(min_length=1, description="Measurement method identifier")
    version: str = Field(min_length=1, description="Measurement method version")
