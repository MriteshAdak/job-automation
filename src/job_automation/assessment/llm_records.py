"""Domain records, request/result envelopes, and proposal models for MATCH-02."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal, Union

from pydantic import Field, field_validator, model_validator

from job_automation.assessment.models import (
    CriterionEvaluation,
    ExclusionOutcome,
    PreferenceOutcome,
    RelevanceAssessmentResult,
)
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.contracts.assessment import Assessment, RequirementFinding
from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMode,
    ContextStrategy,
    FindingStatus,
    HardCriterionResult,
    RequirementCategory,
    RequirementObligation,
)
from job_automation.contracts.errors import ClassifiedError, ValidationIssue
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
)
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexReadRequest,
)
from job_automation.policy.models import EffectivePolicy


class RequirementItem(ContractModel):
    """Source-backed job requirement extracted from a posting."""

    requirement_id: str = Field(min_length=1, description="Stable identifier for requirement")
    text: str = Field(min_length=1, description="Statement of requirement")
    obligation: RequirementObligation = Field(
        default=RequirementObligation.REQUIRED,
        description="Obligation level: required, preferred, or unclear",
    )
    category: RequirementCategory = Field(
        default=RequirementCategory.OTHER,
        description="Domain category of requirement",
    )
    job_evidence: JobEvidenceReference = Field(
        description="Verifiable source reference in posting text",
    )
    qualifiers: list[str] = Field(
        default_factory=list,
        description="Optional modifiers or conditions",
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description="Alternative qualifications (e.g. 'degree OR equivalent experience')",
    )
    threshold: str | None = Field(
        default=None,
        description="Numeric threshold value if specified (e.g. '5')",
    )
    unit: str | None = Field(
        default=None,
        description="Unit for threshold if specified (e.g. 'years')",
    )
    source_status: str = Field(
        default="valid",
        description="Extraction status: 'valid', 'unsupported_extraction', 'unclear'",
    )


class RequirementIssue(ContractModel):
    """Diagnostic issue encountered during requirement extraction or validation."""

    code: str = Field(min_length=1, description="Diagnostic code")
    stage: str = Field(min_length=1, description="Pipeline stage where issue occurred")
    requirement_id: str | None = Field(default=None, description="Affected requirement ID")
    message: str = Field(min_length=1, description="Safe diagnostic description")
    severity: Literal["warning", "error"] = Field(default="warning")


class RequirementSet(ContractModel):
    """Source-backed collection of requirements derived from a posting before retrieval."""

    recipe_version: str = Field(default="v1", description="Requirement extraction recipe version")
    canonical_job_id: uuid.UUID = Field(description="Target canonical job UUID")
    job_revision: str = Field(min_length=1, description="Posting revision or content hash")
    requirements: list[RequirementItem] = Field(
        default_factory=list,
        description="Ordered list of extracted requirements",
    )
    issues: list[RequirementIssue] = Field(
        default_factory=list,
        description="Diagnostic issues recorded during preparation",
    )
    fingerprint: str = Field(
        min_length=1,
        description="Canonical SHA-256 fingerprint over all requirements",
    )
    extractor_version: str = Field(
        default="v1-deterministic",
        description="Version string of the extractor used",
    )


class DeterministicDecisionTrace(ContractModel):
    """Exported trace of deterministic decisions from MATCH-01."""

    evaluator_version: str = Field(default="1.0", description="MATCH-01 evaluator version")
    evaluations: list[CriterionEvaluation] = Field(default_factory=list)
    eligibility_checks: list[dict[str, Any]] = Field(default_factory=list)
    preferences: list[PreferenceOutcome] = Field(default_factory=list)
    exclusions: list[ExclusionOutcome] = Field(default_factory=list)
    relevance: RelevanceAssessmentResult | None = None
    confirmed_hard_failures: list[str] = Field(default_factory=list)
    missing_data_rejections: list[str] = Field(default_factory=list)
    factual_unknowns: list[str] = Field(default_factory=list)
    eligibility_failures: list[str] = Field(default_factory=list)
    eligibility_unknowns: list[str] = Field(default_factory=list)
    exclusion_rejections: list[str] = Field(default_factory=list)

    def has_confirmed_hard_failure(self) -> bool:
        """True if any confirmed factual hard rule failure, eligibility failure, or exclusion occurred."""
        return (
            len(self.confirmed_hard_failures) > 0
            or len(self.eligibility_failures) > 0
            or len(self.exclusion_rejections) > 0
        )

    def has_rejection(self) -> bool:
        """True if the deterministic baseline produced a REJECTED outcome from any source."""
        if self.has_confirmed_hard_failure():
            return True
        if len(self.missing_data_rejections) > 0:
            return True
        if self.relevance is not None and self.relevance.decision == AssessmentDisposition.REJECTED:
            return True
        return False

    def has_missing_data_rejection(self) -> bool:
        """True if rejection was caused by a policy on_missing='fail' rather than confirmed failure."""
        return len(self.missing_data_rejections) > 0

    def has_review_condition(self) -> bool:
        """True if any unresolved factual unknowns or eligibility unknowns require review."""
        if len(self.factual_unknowns) > 0 or len(self.eligibility_unknowns) > 0:
            return True
        if self.relevance is not None and self.relevance.decision == AssessmentDisposition.REVIEW:
            return True
        return False

    def compute_digest(self) -> str:
        """Compute stable SHA-256 digest of this decision trace."""
        data = {
            "evaluator_version": self.evaluator_version,
            "confirmed_hard_failures": sorted(self.confirmed_hard_failures),
            "missing_data_rejections": sorted(self.missing_data_rejections),
            "factual_unknowns": sorted(self.factual_unknowns),
            "eligibility_failures": sorted(self.eligibility_failures),
            "eligibility_unknowns": sorted(self.eligibility_unknowns),
            "exclusion_rejections": sorted(self.exclusion_rejections),
        }
        canonical_bytes = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"


class RequirementFindingProposal(ContractModel):
    """Model-authored assessment proposal for a single requirement."""

    requirement_id: str = Field(min_length=1, description="Requirement identifier cited")
    status: FindingStatus = Field(description="Proposed status: match, gap, or unknown")
    candidate_evidence: list[CandidateEvidenceReference] = Field(
        default_factory=list,
        description="Candidate evidence cited to support finding",
    )
    job_evidence: JobEvidenceReference | None = Field(
        default=None,
        description="Job posting evidence cited if specific passage is referenced",
    )
    reason: str = Field(min_length=1, description="Reasoning for the finding")
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Optional requirement-level fit score on 0-100 scale",
    )

    @field_validator("score", mode="before")
    @classmethod
    def _validate_score_not_bool(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Score cannot be a boolean")
        return v


class AssessmentProposal(ContractModel):
    """Strict bounded model-owned generation output schema.

    Enforces:
    - Extra fields are strictly forbidden (model cannot invent final_disposition or rule_outcomes).
    - Every finding cites a requirement ID.
    - Score is strictly on 0-100 scale if provided.
    """

    model_config = {"extra": "forbid"}

    findings: list[RequirementFindingProposal] = Field(
        default_factory=list,
        description="One finding per admitted requirement",
    )
    relevance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Overall relevance score on 0-100 scale",
    )
    score_scale: Literal["0-100"] | None = Field(
        default=None,
        description="Declared scale for score; required if score is provided",
    )
    summary_reason: str = Field(
        min_length=1,
        description="Concise synthesis explaining overall candidate fit",
    )

    @field_validator("relevance_score", mode="before")
    @classmethod
    def _validate_score_not_bool(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Relevance score cannot be a boolean")
        return v

    @model_validator(mode="after")
    def _validate_score_scale(self) -> AssessmentProposal:
        if self.relevance_score is not None and self.score_scale is None:
            raise ValueError("When relevance_score is provided, score_scale must be '0-100'")
        if self.relevance_score is None and self.score_scale is not None:
            raise ValueError("score_scale cannot be provided without relevance_score")
        return self


class AssessmentLimits(ContractModel):
    """Resource limits and token budgets for model assessment."""

    max_requirements: int = Field(default=20, ge=1, le=50)
    context_limit: int = Field(default=8192, gt=0)
    output_reserve: int = Field(default=1024, ge=0)
    safety_allowance: int = Field(default=64, ge=0)


class AssessmentRequest(ContractModel):
    """Explicit, fully bound request for model-assisted assessment."""

    assessment_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique execution UUID for this assessment attempt",
    )
    canonical_job_id: uuid.UUID = Field(description="Target canonical job UUID")
    posting_revision: str = Field(min_length=1, description="Posting revision or content hash")
    posting: NormalizedPosting = Field(description="Exact normalized posting")
    profile: ProfileSnapshot = Field(description="Approved candidate profile snapshot")
    policy: Union[SearchPolicy, EffectivePolicy] = Field(
        description="Search policy governing evaluation"
    )
    deterministic_baseline: Assessment = Field(
        description="Complete rules-only C11 Assessment from MATCH-01",
    )
    deterministic_trace: DeterministicDecisionTrace = Field(
        description="Detailed trace of deterministic decisions",
    )
    context_strategy: ContextStrategy = Field(
        default=ContextStrategy.JSON,
        description="Context strategy: json or rag",
    )
    purpose: Literal["assessment"] = "assessment"
    model_identifier: str = Field(
        default="local-assessor",
        min_length=1,
        description="Target model identifier",
    )
    model_digest: str | None = Field(
        default=None,
        description="Optional immutable model digest pinned for execution",
    )
    prompt_version: str = Field(default="v1", min_length=1)
    schema_version: str = Field(default="1.0", min_length=1)
    assessment_mode: AssessmentMode = Field(default=AssessmentMode.PRIMARY)
    limits: AssessmentLimits = Field(default_factory=AssessmentLimits)
    retrieval_settings: RetrievalSettings | None = Field(
        default=None,
        description="Retrieval settings for RAG; defaults to DEFAULT_RETRIEVAL_SETTINGS if strategy is RAG",
    )
    inclusion_rule_version: str = Field(default="v1", min_length=1)
    mandatory_policy_version: str = Field(default="v1", min_length=1)
    extractor_mode: Literal["deterministic", "llm"] = Field(
        default="deterministic",
        description="Requirement preparation mode: 'deterministic' (default) or 'llm'",
    )
    index_read_request: IndexReadRequest | None = None
    embedding_config: EmbeddingConfiguration | None = None
    require_exact_measurement: bool = False

    @model_validator(mode="after")
    def _validate_request_integrity(self) -> AssessmentRequest:
        # Check canonical job and revision alignment with baseline
        if self.deterministic_baseline.canonical_job_id != self.canonical_job_id:
            raise ValueError("deterministic_baseline.canonical_job_id must match request.canonical_job_id")
        if self.deterministic_baseline.posting_revision != self.posting_revision:
            raise ValueError("deterministic_baseline.posting_revision must match request.posting_revision")
        if getattr(self.profile, "approval_metadata", None) is None:
            raise ValueError("Candidate profile snapshot must have human approval")
        return self


class AssessmentRunResult(ContractModel):
    """Discriminated outcome envelope: either success with completed C11, or pending result."""

    status: Literal["success", "pending"]
    assessment: Assessment | None = None
    input_fingerprint: str = Field(min_length=1, description="Fingerprint of all output-affecting inputs")
    failed_stage: str | None = None
    error: ClassifiedError | None = None
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    retryable: bool = False
    deterministic_baseline: Assessment | None = None
    audit_references: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_success_pending_exclusivity(self) -> AssessmentRunResult:
        if self.status == "success":
            if self.assessment is None:
                raise ValueError("Successful AssessmentRunResult must include completed assessment")
            if self.failed_stage is not None or self.error is not None:
                raise ValueError("Successful AssessmentRunResult must not have failed_stage or error")
        elif self.status == "pending":
            if self.assessment is not None:
                raise ValueError("Pending AssessmentRunResult must NOT include a completed assessment")
            if self.failed_stage is None:
                raise ValueError("Pending AssessmentRunResult must specify failed_stage")
            if self.error is None:
                raise ValueError("Pending AssessmentRunResult must specify error")
        return self
