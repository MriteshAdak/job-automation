"""C11 Assessment contracts.

Unified assessment outcome covering deterministic rules-only evaluation and
model-assisted relevance assessment. Enforces hard failure precedence and
conditional metadata consistency.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    FindingStatus,
    HardCriterionResult,
    RequirementCategory,
    RequirementObligation,
)
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    EvidenceReference,
    JobEvidenceReference,
)
from job_automation.contracts.models import TokenUsage


class RuleOutcome(ContractModel):
    """Evaluation result for a single hard criterion."""

    criterion_id: str = Field(min_length=1, description="Identifier of the evaluated criterion")
    criterion_name: str = Field(min_length=1, description="Human-readable criterion name")
    result: HardCriterionResult = Field(description="pass, fail, or unknown")
    evidence: EvidenceReference | None = Field(
        default=None,
        description="Optional evidence reference supporting this outcome",
    )
    reason: str = Field(min_length=1, description="Explanation of the evaluation result")


class RequirementFinding(ContractModel):
    """Structured assessment finding for an evaluated job requirement."""

    requirement_id: str = Field(min_length=1, description="Stable requirement identifier")
    requirement_text: str = Field(min_length=1, description="Statement of requirement evaluated")
    obligation: RequirementObligation = Field(
        default=RequirementObligation.REQUIRED,
        description="Obligation level: required, preferred, or unclear",
    )
    category: RequirementCategory = Field(
        default=RequirementCategory.OTHER,
        description="Domain category of requirement",
    )
    status: FindingStatus = Field(description="Finding status: match, gap, or unknown")
    candidate_evidence: list[CandidateEvidenceReference] = Field(
        default_factory=list,
        description="Cited candidate evidence references supporting this finding",
    )
    job_evidence: JobEvidenceReference | None = Field(
        default=None,
        description="Cited job evidence reference supporting this finding",
    )
    reason: str = Field(min_length=1, description="Explanation of finding")
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Optional fit score on 0-100 scale",
    )


class LLMAssessmentMetadata(ContractModel):
    """Metadata recorded when an assessment involves LLM inference."""

    model_identifier: str = Field(min_length=1, description="Model used for assessment")
    prompt_version: str = Field(min_length=1, description="Prompt version used")
    context_strategy: ContextStrategy = Field(
        description="Context strategy used: json or rag"
    )
    context_bundle_ref: str | None = Field(
        default=None,
        description="Reference or hash of the C09 ContextBundle evaluated",
    )
    model_digest: str | None = Field(
        default=None,
        description="Immutable digest of observed model weights",
    )
    prompt_fingerprint: str | None = Field(
        default=None,
        description="Fingerprint of bound generation prompt",
    )
    generation_call_id: uuid.UUID | None = Field(
        default=None,
        description="C10 ModelCall UUID",
    )
    generation_settings: dict[str, Any] = Field(
        default_factory=dict,
        description="Effective generation parameters used",
    )
    token_usage: TokenUsage | None = Field(
        default=None,
        description="Measured prompt and completion token counts",
    )


class Assessment(ContractModel):
    """C11 Job Assessment.

    Complete evaluation outcome combining deterministic rule outcomes and optional
    model-assisted relevance scoring.
    """

    assessment_id: uuid.UUID = Field(description="Unique assessment execution UUID")
    canonical_job_id: uuid.UUID = Field(description="Target canonical job UUID")
    posting_revision: str = Field(min_length=1, description="Posting revision or content hash")
    profile_version: str = Field(min_length=1, description="Version of candidate profile used")
    policy_version: str = Field(min_length=1, description="Version of search policy used")
    assessment_method: AssessmentMethod = Field(
        description="Method used: rules (deterministic only) or llm (model-assisted)"
    )
    rule_outcomes: list[RuleOutcome] = Field(
        default_factory=list,
        description="Per-criterion outcomes for all evaluated hard rules",
    )
    requirement_findings: list[RequirementFinding] = Field(
        default_factory=list,
        description="Per-requirement findings for evaluated job requirements",
    )
    relevance_decision: AssessmentDisposition = Field(
        description="Relevance disposition: eligible, review, or rejected"
    )
    relevance_score: float | None = Field(
        default=None,
        ge=0.0,
        description="Optional numeric relevance score; a ranking signal, not offer probability",
    )
    score_scale: str | None = Field(
        default=None,
        description="Declared scale for the score (e.g. '0-100'); required if score is provided",
    )
    identified_gaps: list[str] = Field(
        default_factory=list,
        description="Identified candidate requirement gaps or missing qualifications",
    )
    identified_unknowns: list[str] = Field(
        default_factory=list,
        description="Unverified requirements or missing advert facts requiring human review",
    )
    summary_reason: str = Field(
        min_length=1,
        description="Concise summary explanation of the final disposition",
    )
    final_disposition: AssessmentDisposition = Field(
        description="Final disposition: eligible, review, or rejected"
    )
    model_metadata: LLMAssessmentMetadata | None = Field(
        default=None,
        description="Inference metadata; required when assessment_method is 'llm'",
    )
    validation_issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="Non-fatal validation or extraction issues recorded during assessment",
    )
    assessment_input_fingerprint: str | None = Field(
        default=None,
        description="Canonical SHA-256 fingerprint of all output-affecting inputs",
    )
    deterministic_trace_ref: str | None = Field(
        default=None,
        description="Reference or digest of the deterministic decision trace",
    )

    @model_validator(mode="after")
    def _validate_metadata_consistency(self) -> Assessment:
        # LLM assessment requires model_metadata
        if self.assessment_method == AssessmentMethod.LLM and self.model_metadata is None:
            raise ValueError(
                "Assessment with assessment_method='llm' must provide model_metadata"
            )

        # Relevance score requires documented score_scale
        if self.relevance_score is not None and self.score_scale is None:
            raise ValueError(
                "When relevance_score is provided, score_scale must be documented"
            )

        # Hard failure precedence rule: a hard failure cannot result in eligible disposition
        has_hard_failure = any(
            ro.result == HardCriterionResult.FAIL for ro in self.rule_outcomes
        )
        if has_hard_failure and self.final_disposition == AssessmentDisposition.ELIGIBLE:
            raise ValueError(
                "A confirmed hard criterion failure cannot be overridden to eligible disposition"
            )

        return self

