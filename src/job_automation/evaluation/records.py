"""Data contracts and domain records for evaluation, comparisons, and metrics (EVAL-01-S01).

Enforces:
- Schema versioning.
- Strict pairing controls (identical profile, model, prompt, decoding settings).
- Discriminative representation of successful, failed, and pending execution states.
- Separation of gold labels, model outputs, and reviewer feedback.
- Explicit non-publication invariants.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Sequence
from pydantic import Field, field_validator, model_validator

from job_automation.assessment.llm_records import (
    AssessmentProposal,
    DeterministicDecisionTrace,
)
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.contracts.assessment import Assessment, RequirementFinding
from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMode,
    ContextStrategy,
    FindingStatus,
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
from job_automation.evaluation.errors import MismatchedArmControlError
from job_automation.evaluation.fingerprints import (
    canonical_json_bytes,
    compute_canonical_fingerprint,
    compute_sha256,
)
from job_automation.evaluation.settings import EVAL_SCHEMA_VERSION, METRIC_SPEC_VERSION


class DependencyGate(ContractModel):
    """Status record for an external dependency gate (EG1 through EG5)."""

    gate_id: Literal["EG1", "EG2", "EG3", "EG4", "EG5"]
    name: str
    owner: str
    status: Literal["SATISFIED_OFFLINE", "PENDING_LIVE", "DEFERRED", "UNAVAILABLE"]
    evidence: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DependencyGateRegister(ContractModel):
    """Register of concrete integration gates for EVAL-01."""

    eg1_exact_frozen_inputs: DependencyGate = Field(
        default_factory=lambda: DependencyGate(
            gate_id="EG1",
            name="Exact frozen inputs",
            owner="RUN/DATA/IDENTITY",
            status="SATISFIED_OFFLINE",
            evidence="RUN-01 posting_bindings and C06 snapshot export verified offline.",
        )
    )
    eg2_comparable_model_execution: DependencyGate = Field(
        default_factory=lambda: DependencyGate(
            gate_id="EG2",
            name="Comparable model execution",
            owner="MATCH/CONTEXT/LLM",
            status="SATISFIED_OFFLINE",
            evidence="Shared selector, deterministic extractor, and local model provider admission verified.",
        )
    )
    eg3_observable_evidence: DependencyGate = Field(
        default_factory=lambda: DependencyGate(
            gate_id="EG3",
            name="Observable evidence capture",
            owner="MATCH/CONTEXT/LLM",
            status="SATISFIED_OFFLINE",
            evidence="Retrieval trace, admitted bundle, proposal, and validation issues captured.",
        )
    )
    eg4_run_integration_and_isolation: DependencyGate = Field(
        default_factory=lambda: DependencyGate(
            gate_id="EG4",
            name="RUN integration and publication isolation",
            owner="RUN/SYNC",
            status="SATISFIED_OFFLINE",
            evidence="Dedicated evaluation DB, zero Salesforce gateway instantiation, publication blocked.",
        )
    )
    eg5_live_execution: DependencyGate = Field(
        default_factory=lambda: DependencyGate(
            gate_id="EG5",
            name="Live model service execution",
            owner="MODEL-01/02",
            status="PENDING_LIVE",
            evidence="Offline scripted and deterministic test transports pass; live local Ollama benchmark pending.",
        )
    )


class GoldRequirementLabel(ContractModel):
    """Ground truth annotation for a single job requirement."""

    requirement_id: str = Field(min_length=1, description="Target requirement identifier")
    text: str = Field(min_length=1, description="Statement of requirement")
    obligation: RequirementObligation = Field(default=RequirementObligation.REQUIRED)
    category: RequirementCategory = Field(default=RequirementCategory.OTHER)
    source_spans: list[JobEvidenceReference] = Field(
        default_factory=list,
        description="Verifiable source quotations in posting",
    )
    sufficient_evidence_sets: list[list[str]] = Field(
        default_factory=list,
        description="Alternative candidate fact ID sets; all fact IDs in at least one set must be cited for sufficient support",
    )
    contradictory_fact_ids: list[str] = Field(
        default_factory=list,
        description="Candidate evidence fact IDs directly contradicting requirement",
    )
    unknown_if_missing: bool = Field(
        default=True,
        description="True if absence of evidence constitutes unknown/unsupported rather than proven gap",
    )
    gold_status: FindingStatus = Field(
        default=FindingStatus.MATCH,
        description="Expected finding status given the profile facts",
    )
    notes: str | None = None


class GoldLabelRevision(ContractModel):
    """Immutable, versioned ground-truth adjudication record for a case."""

    label_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    case_id: str = Field(min_length=1)
    revision_number: int = Field(default=1, ge=1)
    requirements: list[GoldRequirementLabel] = Field(default_factory=list)
    gold_disposition: AssessmentDisposition = Field(description="Adjudicated overall disposition")
    expected_score: float | None = Field(default=None, ge=0.0, le=100.0)
    expected_score_scale: Literal["0-100"] | None = Field(default=None)
    hard_failure_reasons: list[str] = Field(default_factory=list)
    adjudication_status: Literal["draft", "adjudicated", "disputed"] = "adjudicated"
    reviewer: str = Field(default="synthetic-adjudicator")
    rationale: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    label_fingerprint: str = Field(default="")

    @model_validator(mode="after")
    def _compute_fingerprint(self) -> GoldLabelRevision:
        if not self.label_fingerprint:
            summary = {
                "case_id": self.case_id,
                "revision_number": self.revision_number,
                "disposition": self.gold_disposition.value,
                "requirements": [
                    {
                        "req_id": r.requirement_id,
                        "status": r.gold_status.value,
                        "sets": sorted([sorted(s) for s in r.sufficient_evidence_sets]),
                    }
                    for r in self.requirements
                ],
            }
            object.__setattr__(self, "label_fingerprint", compute_canonical_fingerprint(summary))
        return self


class EvaluationCase(ContractModel):
    """Self-contained, frozen evaluation test case combining input posting, profile, policy, and gold labels."""

    case_id: str = Field(min_length=1)
    canonical_job_id: uuid.UUID
    posting_revision: str = Field(min_length=1)
    posting: NormalizedPosting
    profile: ProfileSnapshot
    policy: SearchPolicy
    deterministic_baseline: Assessment | None = None
    deterministic_trace: DeterministicDecisionTrace | None = None
    gold_label: GoldLabelRevision
    split_assignment: Literal["development", "held_out"] = "development"
    opportunity_group_id: str = Field(
        min_length=1,
        description="Grouping identifier (e.g. canonical_job_id or employer group) ensuring no split leakage",
    )
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    case_fingerprint: str = Field(default="")

    @model_validator(mode="after")
    def _validate_case_integrity(self) -> EvaluationCase:
        if not self.case_fingerprint:
            summary = {
                "case_id": self.case_id,
                "canonical_job_id": str(self.canonical_job_id),
                "posting_revision": self.posting_revision,
                "profile_candidate_id": str(self.profile.candidate_id),
                "profile_version": self.profile.profile_version,
                "policy_version": self.policy.policy_version,
                "gold_label_fingerprint": self.gold_label.label_fingerprint,
                "opportunity_group_id": self.opportunity_group_id,
                "split": self.split_assignment,
            }
            object.__setattr__(self, "case_fingerprint", compute_canonical_fingerprint(summary))
        return self


class ExperimentManifest(ContractModel):
    """Immutable control manifest defining the exact parameters of a paired evaluation."""

    experiment_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_name: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    corpus_version: str = Field(default="1.0", min_length=1)
    split_name: Literal["development", "held_out", "all"] = "development"
    case_ids: list[str] = Field(min_length=1)
    
    # Shared controls frozen for both arms
    profile_snapshot_hash: str = Field(min_length=1)
    search_policy_fingerprint: str = Field(min_length=1)
    model_identifier: str = Field(min_length=1)
    model_digest: str = Field(min_length=1)
    effective_decoding_settings: dict[str, Any] = Field(default_factory=lambda: {"temperature": 0.0, "seed": 42})
    prompt_version: str = Field(default="v1", min_length=1)
    prompt_template_hash: str = Field(default="sha256:default_prompt_template")
    schema_version: str = Field(default=EVAL_SCHEMA_VERSION, min_length=1)
    context_limit: int = Field(default=8192, gt=0)
    output_reserve: int = Field(default=1024, ge=0)
    safety_allowance: int = Field(default=64, ge=0)
    extractor_mode: Literal["deterministic", "llm"] = Field(default="deterministic")
    extractor_version: str = Field(default="v1-deterministic")
    
    # RAG treatment configuration
    rag_retrieval_settings: RetrievalSettings | None = None
    rag_index_version: str | None = None
    rag_embedding_digest: str | None = None
    
    # Evaluation execution controls
    metric_spec_version: str = Field(default=METRIC_SPEC_VERSION, min_length=1)
    repetitions_per_pair: int = Field(default=1, ge=1)
    order_randomization_seed: int = Field(default=42)
    software_version: str = Field(default="1.0.0")
    manifest_fingerprint: str = Field(default="")

    @model_validator(mode="after")
    def _compute_manifest_fingerprint(self) -> ExperimentManifest:
        if not self.manifest_fingerprint:
            d = {
                "experiment_id": str(self.experiment_id),
                "name": self.experiment_name,
                "corpus_version": self.corpus_version,
                "split": self.split_name,
                "cases": sorted(self.case_ids),
                "profile_hash": self.profile_snapshot_hash,
                "policy_fp": self.search_policy_fingerprint,
                "model_id": self.model_identifier,
                "model_digest": self.model_digest,
                "decoding": self.effective_decoding_settings,
                "prompt_v": self.prompt_version,
                "prompt_template_hash": self.prompt_template_hash,
                "context_limit": self.context_limit,
                "extractor_mode": self.extractor_mode,
                "rag_settings": self.rag_retrieval_settings.model_dump(mode="json") if self.rag_retrieval_settings else None,
                "rag_index_version": self.rag_index_version,
                "rag_embedding_digest": self.rag_embedding_digest,
                "repetitions": self.repetitions_per_pair,
                "seed": self.order_randomization_seed,
            }
            object.__setattr__(self, "manifest_fingerprint", compute_canonical_fingerprint(d))
        return self


class ArmAttempt(ContractModel):
    """Result of evaluating a single context strategy arm for a case."""

    attempt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    pair_id: uuid.UUID
    case_id: str
    strategy: ContextStrategy
    repetition_index: int = 0
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    execution_status: Literal["success", "pending", "failed", "overflow"] = "success"
    raw_proposal: AssessmentProposal | None = None
    final_assessment: Assessment | None = None
    error: ClassifiedError | None = None
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    stage_latencies_ms: dict[str, float] = Field(default_factory=dict)
    token_counts: dict[str, Any] = Field(default_factory=dict)
    captured_trace: dict[str, Any] = Field(default_factory=dict)
    prompt_bytes_hash: str = ""
    input_fingerprint: str = ""


class PairResult(ContractModel):
    """Paired comparison outcome holding both JSON and RAG arm attempts."""

    pair_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_id: uuid.UUID
    case_id: str
    repetition_index: int = 0
    execution_order: list[ContextStrategy] = Field(
        description="Order in which arms were evaluated (e.g. [JSON, RAG] or [RAG, JSON])",
    )
    baseline_disposition: AssessmentDisposition
    json_arm: ArmAttempt
    rag_arm: ArmAttempt
    pair_completed: bool = False
    strategy_delta_score: float | None = None
    disposition_agreement: bool | None = None
    validity_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_pair(self) -> PairResult:
        pair_completed = (
            self.json_arm.execution_status == "success"
            and self.rag_arm.execution_status == "success"
            and self.json_arm.final_assessment is not None
            and self.rag_arm.final_assessment is not None
        )
        object.__setattr__(self, "pair_completed", pair_completed)
        if pair_completed:
            asmt_j = self.json_arm.final_assessment
            asmt_r = self.rag_arm.final_assessment
            assert asmt_j is not None and asmt_r is not None
            object.__setattr__(
                self,
                "disposition_agreement",
                asmt_j.final_disposition == asmt_r.final_disposition,
            )
            if asmt_j.relevance_score is not None and asmt_r.relevance_score is not None:
                object.__setattr__(
                    self,
                    "strategy_delta_score",
                    round(asmt_j.relevance_score - asmt_r.relevance_score, 2),
                )
        else:
            object.__setattr__(self, "strategy_delta_score", None)
            object.__setattr__(self, "disposition_agreement", None)
        return self


class ReviewCorrection(ContractModel):
    """Human reviewer correction or annotation update."""

    correction_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    case_id: str
    arm_id: uuid.UUID | None = None
    reviewer_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target_type: Literal[
        "requirement_extraction",
        "hard_rule",
        "retrieval",
        "packing_budget",
        "model_finding",
        "unsupported_claim",
        "label_error",
    ]
    old_value: dict[str, Any]
    new_value: dict[str, Any]
    reason: str
    supporting_evidence: list[CandidateEvidenceReference] = Field(default_factory=list)
    active_review_seconds: float = 0.0
    adjudication_status: Literal["pending", "adjudicated", "rejected"] = "pending"


class SampleManifest(ContractModel):
    """Reproducible sampling record for rejected-job sampling."""

    sample_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    population_cohort_id: str
    population_size: int
    sample_size: int
    sampling_seed: int
    stratification_summary: dict[str, int]
    inclusion_probabilities: dict[str, float]
    selected_case_ids: list[str]
    frame_hash: str


class MetricReport(ContractModel):
    """Comprehensive evaluation metric report comparing JSON and RAG context strategies."""

    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_id: uuid.UUID
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metric_spec_version: str = Field(default=METRIC_SPEC_VERSION)
    total_cases: int
    completed_pairs: int
    incomplete_pairs: int
    json_arm_completion_rate: float
    rag_arm_completion_rate: float
    strategy_metrics: dict[str, Any]
    paired_deltas: dict[str, Any]
    confusion_matrices: dict[str, Any]
    attribution_breakdown: dict[str, Any]
    sample_limitations: list[str] = Field(default_factory=list)
    proposed_targets: dict[str, Any] = Field(default_factory=dict)
