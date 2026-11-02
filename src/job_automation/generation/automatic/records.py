"""Data contracts, companion envelopes, and record models for AUTO-02.

Defines:
- AutomaticDraftPolicy: versioned, opt-in drafting policy and bounds.
- AutomaticDraftCandidate: input envelope capturing assessment, posting, and candidate facts.
- AutomaticDraftDecision: inspectable policy decision and outcome with structured reasons.
- AutomaticDraftIntent: durable, immutable generation request intent with stable client key.
- AutomaticDraftReservation: quota reservation tracking document-request units.
- AutomaticRequestBinding: durable one-to-one link between C13 request and automatic intent.
- AutomaticDraftEvaluationReport: safe run evaluation report with documented units.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    DocumentType,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.profile import ProfileSnapshot


class AutomaticDraftOutcome(StrEnum):
    """Categorized outcome of automatic drafting policy evaluation."""

    ADMITTED = "admitted"
    REUSED = "reused"
    BELOW_THRESHOLD = "below_threshold"
    INELIGIBLE = "ineligible"
    REVIEW_REQUIRED = "review_required"
    SUPPRESSED = "suppressed"
    DEFERRED = "deferred"
    BLOCKED = "blocked"
    DISABLED = "disabled"
    EXCLUDED = "excluded"


class SubmissionState(StrEnum):
    """State of an AutomaticDraftIntent submission lifecycle."""

    RESERVED = "reserved"
    SENDING = "sending"
    UNCERTAIN = "uncertain"
    ACKNOWLEDGED = "acknowledged"
    HELD = "held"
    RELEASED = "released"
    FAILED = "failed"


class ReservationStatus(StrEnum):
    """Status of an automatic quota reservation."""

    ACTIVE = "active"
    CONSUMED = "consumed"
    RELEASED = "released"


class RepeatMode(StrEnum):
    """Repeat generation strategy for a candidate and canonical opportunity."""

    FIRST_ONLY = "first_only"
    ON_MATERIAL_CHANGE = "on_material_change"


class AutomaticVolumeLimits(ContractModel):
    """Finite, non-negative volume limits for automatic draft creation."""

    max_requests_per_run: int = Field(
        default=5,
        ge=0,
        description="Maximum logical requests created in one evaluation run",
    )
    max_requests_per_window: int = Field(
        default=10,
        ge=0,
        description="Maximum logical requests admitted in a rolling window",
    )
    window_hours: float = Field(
        default=24.0,
        gt=0.0,
        description="Rolling window duration in civil hours",
    )
    max_requests_per_job: int = Field(
        default=2,
        ge=0,
        description="Maximum logical requests per candidate/job across material changes",
    )
    max_outstanding_requests: int = Field(
        default=5,
        ge=0,
        description="Maximum concurrent unreviewed/in-flight automatic requests",
    )


class DocumentVariantConfig(ContractModel):
    """Specification of a document variant admitted for automatic drafting."""

    document_type: DocumentType = Field(description="Document type: cv or cover_letter")
    target_language: str = Field(default="de", description="Target document language (e.g. 'de', 'en')")
    template_id: str = Field(default="standard-cv", min_length=1, description="Layout template identifier")
    context_strategy: ContextStrategy = Field(default=ContextStrategy.JSON, description="Context strategy: json or rag")
    formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"], description="Rendered file formats")
    content_specification: str | None = Field(default=None, description="Supplemental content recipe/spec")
    layout_id: str | None = Field(default=None, description="Physical layout identifier")
    layout_version: str | None = Field(default=None, description="Layout version")
    recipe_id: str | None = Field(default=None, description="Content generation recipe ID")
    recipe_version: str | None = Field(default=None, description="Content generation recipe version")

    @field_validator("formats")
    @classmethod
    def _validate_formats(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("DocumentVariantConfig formats must not be empty")
        valid = {"docx", "pdf"}
        for fmt in v:
            if fmt.lower() not in valid:
                raise ValueError(f"Unsupported format '{fmt}'; must be 'docx' or 'pdf'")
        return [fmt.lower() for fmt in sorted(v)]


class RepeatPolicy(ContractModel):
    """Repeat generation rules for changes to previously drafted jobs."""

    mode: RepeatMode = Field(default=RepeatMode.FIRST_ONLY, description="first_only or on_material_change")
    allowed_change_classes: list[str] = Field(
        default_factory=lambda: ["posting_content", "profile_content", "document_options", "generation_recipe"],
        description="Permitted material change classes that authorize new drafts under on_material_change",
    )
    cooldown_hours: float = Field(
        default=24.0,
        ge=0.0,
        description="Minimum cooldown hours between drafts of the same canonical job",
    )


class AutomaticDraftPolicy(ContractModel):
    """C17 Automatic drafting policy configuration.

    Governs threshold evaluation, volume limits, freshness constraints,
    allowed candidate states, and repeat generation rules.
    Disabled by default; requires explicit opt-in configuration.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    schema_version: str = Field(default="1.0", description="Contract schema version")
    policy_id: str = Field(default="auto-draft-v1", min_length=1, description="Policy identifier")
    policy_version: str = Field(default="v1.0", min_length=1, description="Immutable policy version")
    enabled: bool = Field(default=False, description="Opt-in flag: False disables all automatic draft creation")
    candidate_id: uuid.UUID = Field(description="Authoritative candidate UUID scope")
    salesforce_org_id: str = Field(min_length=15, max_length=18, description="Target Salesforce Org ID scope")
    minimum_relevance_score: float = Field(
        default=75.0,
        ge=0.0,
        le=100.0,
        description="Relevance score threshold on 0-100 scale (score >= threshold qualifies)",
    )
    score_scale: str = Field(default="0-100", description="Declared score scale")
    allowed_application_states: list[str] = Field(
        default_factory=lambda: ["New", "Shortlisted"],
        description="Candidate-owned application states permitting automatic draft requests",
    )
    max_assessment_age_hours: float = Field(
        default=72.0,
        gt=0.0,
        description="Maximum age of MATCH-02 assessment in hours",
    )
    max_availability_age_hours: float = Field(
        default=48.0,
        gt=0.0,
        description="Maximum age of availability observation in hours",
    )
    max_candidate_control_age_hours: float = Field(
        default=24.0,
        gt=0.0,
        description="Maximum age of candidate status / opt-out observation in hours",
    )
    clock_skew_tolerance_seconds: int = Field(
        default=60,
        ge=0,
        description="Allowed clock skew in seconds when comparing timestamps",
    )
    volume_limits: AutomaticVolumeLimits = Field(default_factory=AutomaticVolumeLimits)
    document_variants: list[DocumentVariantConfig] = Field(
        default_factory=list,
        description="Document variants to create (e.g. CV, Cover Letter)",
    )
    repeat_policy: RepeatPolicy = Field(default_factory=RepeatPolicy)
    policy_engine_version: str = Field(default="1.0", description="Engine algorithm version")
    policy_content_hash: str | None = Field(
        default=None,
        description="SHA-256 digest of canonical policy content",
    )

    @model_validator(mode="after")
    def _validate_policy(self) -> AutomaticDraftPolicy:
        if math.isnan(self.minimum_relevance_score) or math.isinf(self.minimum_relevance_score):
            raise ValueError("minimum_relevance_score must be a finite float")
        if self.score_scale != "0-100":
            raise ValueError(f"Unsupported score_scale '{self.score_scale}'; must be '0-100'")
        if self.enabled:
            if not self.document_variants:
                raise ValueError("Enabled AutomaticDraftPolicy must specify at least one document variant")
            if not self.allowed_application_states:
                raise ValueError("Enabled AutomaticDraftPolicy must specify allowed_application_states")
            types = [v.document_type for v in self.document_variants]
            if len(types) != len(set(types)):
                raise ValueError("document_variants contains duplicate document_type entries")

        # Compute content hash if missing
        if self.policy_content_hash is None:
            content_dict = self.model_dump(exclude={"policy_content_hash"}, mode="json")
            canonical_bytes = json.dumps(content_dict, sort_keys=True).encode("utf-8")
            object.__setattr__(self, "policy_content_hash", hashlib.sha256(canonical_bytes).hexdigest())

        return self


class AutomaticDraftCandidate(ContractModel):
    """Authoritative input envelope presented to AUTO-02 for evaluation."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    candidate_id: uuid.UUID = Field(description="Candidate UUID")
    salesforce_org_id: str = Field(description="Salesforce Org ID")
    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    lineage_job_ids: list[uuid.UUID] = Field(default_factory=list, description="Associated alias/split canonical IDs")
    assessment_id: uuid.UUID = Field(description="Selected C11 Assessment UUID")
    assessment_input_fingerprint: str = Field(description="SHA-256 MATCH-02 assessment input fingerprint")
    assessment_disposition: AssessmentDisposition = Field(description="C11 disposition (eligible, review, rejected)")
    assessment_method: str = Field(default="llm", description="Assessment method: 'llm' or 'rules'")
    relevance_score: float | None = Field(default=None, description="Numeric relevance score on 0-100 scale")
    score_scale: str | None = Field(default="0-100", description="Score scale")
    evaluated_at: UtcDatetime = Field(description="Timestamp when assessment was performed")
    posting_revision_id: str = Field(description="Posting revision UUID or ID")
    posting_revision_hash: str = Field(description="SHA-256 posting revision hash")
    normalized_content_hash: str = Field(description="SHA-256 material content hash of normalized posting")
    posting_snapshot: NormalizedPosting | None = Field(default=None, description="Normalized posting snapshot")
    profile_version: str = Field(description="Approved candidate profile version")
    profile_digest: str = Field(description="Approved profile snapshot content digest")
    profile_snapshot: ProfileSnapshot | None = Field(default=None, description="Approved profile snapshot")
    search_policy_version: str = Field(description="C02 SearchPolicy version used for assessment")
    search_policy_hash: str = Field(description="SHA-256 C02 SearchPolicy content hash")
    availability_status: PostingAvailability = Field(description="Current availability status")
    availability_observed_at: UtcDatetime | None = Field(default=None, description="When availability was observed")
    candidate_application_state: str | None = Field(
        default=None,
        description="Current candidate-owned application state (e.g. 'New', 'Shortlisted')",
    )
    candidate_opted_out: bool = Field(default=False, description="Whether candidate has explicitly opted out")
    candidate_control_observed_at: UtcDatetime | None = Field(
        default=None,
        description="When candidate application state and opt-out were observed",
    )
    run_id: uuid.UUID | None = Field(default=None, description="Authoritative evaluation/pipeline run UUID")
    run_mode: str = Field(default="production", description="'production', 'evaluation', or 'comparison'")
    is_authoritative_selection: bool = Field(default=True, description="Whether this is the RUN-01 selected final")
    identified_unknowns: list[str] = Field(default_factory=list, description="Identified unknowns from assessment")
    validation_issues: list[str] = Field(default_factory=list, description="Assessment validation issues")
    deterministic_trace_ref: str | None = Field(default=None, description="Trace reference from deterministic baseline")
    rule_coverage_complete: bool = Field(default=True, description="Whether all required C02 criteria were evaluated")


class AutomaticDraftDecision(ContractModel):
    """Immutable policy decision explaining the outcome of evaluating a candidate."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    decision_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique decision UUID")
    candidate_id: uuid.UUID = Field(description="Candidate UUID")
    salesforce_org_id: str = Field(description="Salesforce Org ID")
    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    evaluation_run_id: uuid.UUID = Field(description="Logical evaluation run UUID")
    evaluation_attempt_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Evaluation attempt UUID")
    policy_id: str = Field(description="Evaluated policy ID")
    policy_version: str = Field(description="Evaluated policy version")
    policy_content_hash: str = Field(description="Evaluated policy content hash")
    decision_input_fingerprint: str = Field(description="SHA-256 decision-input fingerprint")
    outcome: AutomaticDraftOutcome = Field(description="Outcome classification")
    reason_codes: list[str] = Field(default_factory=list, description="Structured reason codes")
    summary_reason: str = Field(description="Human-readable explanation of decision")
    evaluated_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of evaluation",
    )
    relevance_score: float | None = Field(default=None, description="Observed relevance score")
    threshold_applied: float | None = Field(default=None, description="Threshold applied")
    assessment_ref: uuid.UUID | None = Field(default=None, description="Associated assessment UUID")
    existing_intent_key: str | None = Field(default=None, description="Client key of prior intent if reused/duplicate")
    existing_request_id: uuid.UUID | None = Field(default=None, description="Local C13 UUID of prior request")
    proposed_document_types: list[DocumentType] = Field(
        default_factory=list,
        description="Document types proposed if admitted",
    )
    quota_snapshot: dict[str, Any] = Field(default_factory=dict, description="Snapshot of quota state")
    review_route: str | None = Field(default=None, description="Inspection or review link")


class AutomaticDraftIntent(ContractModel):
    """Durable creation intent for a single document request."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    intent_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique intent UUID")
    client_request_key: str = Field(min_length=1, description="Unique namespaced client key (auto02:v1:<digest>)")
    candidate_id: uuid.UUID = Field(description="Candidate UUID")
    salesforce_org_id: str = Field(description="Salesforce Org ID")
    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    document_type: DocumentType = Field(description="Document type (cv or cover_letter)")
    target_language: str = Field(default="de", description="Target language")
    template_id: str = Field(default="standard-cv", description="Layout template ID")
    context_strategy: ContextStrategy = Field(default=ContextStrategy.JSON, description="Context strategy")
    formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"], description="Render formats")
    material_generation_fingerprint: str = Field(description="SHA-256 material generation fingerprint")
    policy_id: str = Field(description="Policy ID")
    policy_version: str = Field(description="Policy version")
    policy_content_hash: str = Field(description="Policy content hash")
    decision_id: uuid.UUID = Field(description="Originating decision UUID")
    request_payload_digest: str = Field(description="SHA-256 digest of immutable request payload")
    request_payload_json: str = Field(description="Serialized immutable payload parameters")
    submission_state: SubmissionState = Field(
        default=SubmissionState.RESERVED,
        description="Submission lifecycle state",
    )
    salesforce_request_id: str | None = Field(default=None, description="Associated remote Salesforce record ID")
    local_request_id: uuid.UUID | None = Field(default=None, description="Associated local C13 request UUID")
    attempt_count: int = Field(default=0, ge=0, description="Submission attempt count")
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )
    updated_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp",
    )


class AutomaticDraftReservation(ContractModel):
    """Atomic quota reservation record."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    reservation_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique reservation UUID")
    candidate_id: uuid.UUID = Field(description="Candidate UUID")
    salesforce_org_id: str = Field(description="Salesforce Org ID")
    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    evaluation_run_id: uuid.UUID = Field(description="Evaluation run UUID")
    intent_id: uuid.UUID = Field(description="Associated intent UUID")
    client_request_key: str = Field(description="Associated client request key")
    document_units: int = Field(default=1, ge=1, description="Logical document request units charged")
    status: ReservationStatus = Field(default=ReservationStatus.ACTIVE, description="Reservation status")
    reserved_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When capacity was reserved",
    )
    released_at: UtcDatetime | None = Field(default=None, description="When capacity was released")
    release_reason: str | None = Field(default=None, description="Reason for release")


class AutomaticRequestBinding(ContractModel):
    """Durable one-to-one association between a C13 GenerationRequest and an AutomaticDraftIntent."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    binding_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique binding UUID")
    local_request_id: uuid.UUID = Field(description="C13 GenerationRequest request_id")
    intent_id: uuid.UUID = Field(description="AutomaticDraftIntent intent_id")
    client_request_key: str = Field(description="Stable client request key")
    candidate_id: uuid.UUID = Field(description="Candidate UUID")
    salesforce_org_id: str = Field(description="Salesforce Org ID")
    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    policy_id: str = Field(description="Originating policy ID")
    policy_version: str = Field(description="Originating policy version")
    policy_content_hash: str = Field(description="Originating policy content hash")
    expected_assessment_id: uuid.UUID = Field(description="Expected authoritative assessment UUID")
    expected_assessment_fingerprint: str = Field(description="Expected assessment input fingerprint")
    expected_material_fingerprint: str = Field(description="Expected material generation fingerprint")
    expected_posting_revision_hash: str = Field(description="Expected posting revision hash")
    expected_profile_version: str = Field(description="Expected profile version")
    expected_profile_digest: str = Field(description="Expected profile content digest")
    expected_search_policy_version: str = Field(description="Expected C02 search policy version")
    expected_search_policy_hash: str = Field(description="Expected C02 search policy hash")
    revalidation_receipt: dict[str, Any] | None = Field(
        default=None,
        description="Preflight revalidation receipt written at claim/freeze",
    )
    created_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )


class AutomaticDraftEvaluationReport(ContractModel):
    """Safe, inspectable summary report of an automatic draft evaluation execution."""

    model_config = ConfigDict(frozen=False, extra="forbid")

    run_id: uuid.UUID = Field(description="Evaluation run UUID")
    policy_id: str = Field(description="Policy ID")
    policy_version: str = Field(description="Policy version")
    evaluated_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Execution timestamp",
    )
    total_candidates_evaluated: int = Field(default=0, ge=0)
    jobs_by_outcome: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of unique canonical jobs by outcome",
    )
    requests_by_outcome: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of logical document requests by outcome",
    )
    admitted_intents: list[str] = Field(default_factory=list, description="Client keys of newly admitted intents")
    reused_intents: list[str] = Field(default_factory=list, description="Client keys of reused existing intents")
    held_decisions: list[str] = Field(default_factory=list, description="Decision UUIDs requiring review")
    deferred_decisions: list[str] = Field(default_factory=list, description="Decision UUIDs deferred due to volume limits")
    quota_usage: dict[str, Any] = Field(default_factory=dict, description="Active quota consumption snapshot")
    errors: list[str] = Field(default_factory=list, description="Errors encountered during execution")


def export_schemas(output_dir: Path) -> list[Path]:
    """Export JSON Schema definitions for AUTO-02 contracts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []

    models = [
        ("automatic_draft_policy.schema.json", AutomaticDraftPolicy),
        ("automatic_draft_candidate.schema.json", AutomaticDraftCandidate),
        ("automatic_draft_decision.schema.json", AutomaticDraftDecision),
        ("automatic_draft_intent.schema.json", AutomaticDraftIntent),
        ("automatic_draft_reservation.schema.json", AutomaticDraftReservation),
        ("automatic_request_binding.schema.json", AutomaticRequestBinding),
        ("automatic_draft_evaluation_report.schema.json", AutomaticDraftEvaluationReport),
    ]

    for fname, model_cls in models:
        p = output_dir / fname
        schema = model_cls.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://job-automation.local/schemas/v1/{fname}"
        p.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        exported.append(p)

    return exported
