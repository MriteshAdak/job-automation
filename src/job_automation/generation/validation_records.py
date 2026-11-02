"""Versioned validation contracts, reports, and gate authorizations (GEN-04-S01)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.enums import DocumentType
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.evidence import EvidenceReference


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

SEMANTIC_LIMITS_NOTICE = (
    "Source references and code checks verify traceability to supplied inputs. "
    "They do not certify real-world accuracy, factual completeness, or that generated "
    "sentences are entailed by their sources. Structural excerpts may omit surrounding "
    "qualifications or imply unintended causality. Human semantic review remains "
    "mandatory before document approval or use."
)


class ValidationInputBinding(ContractModel):
    """Verified input binding tying the draft to exact upstream frozen receipts."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    request_id: uuid.UUID
    candidate_id: uuid.UUID
    canonical_job_id: uuid.UUID
    draft_id: uuid.UUID
    draft_version: str
    draft_schema_version: str
    draft_hash: str
    receipt_id: uuid.UUID
    receipt_hash: str
    seal_id: str
    seal_hash: str
    manifest_id: str
    manifest_hash: str
    profile_version: str
    profile_snapshot_digest: str
    posting_revision_id: uuid.UUID
    posting_revision_hash: str
    context_receipt_id: uuid.UUID
    context_hash: str
    admitted_fact_ids: list[uuid.UUID] = Field(default_factory=list)
    document_type: DocumentType
    purpose: str
    target_language: Literal["de", "en"]
    template_id: str
    template_version: str
    template_content_digest: str
    rule_set_id: str
    rule_set_version: str
    rule_set_digest: str
    binding_hash: str


class ValidationContentRequirements(ContractModel):
    """Content specification requirements pinned for a template and document type."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    policy_id: Literal["gen04-extractive-v1"] = "gen04-extractive-v1"
    template_id: Literal["content-basic", "content-compact"]
    document_type: DocumentType
    required_sections: list[str]
    allowed_optional_sections: list[str]
    allowed_section_order: list[str]
    policy_digest: str


def compute_policy_digest(template_id: str, document_type: DocumentType,
                          required_sections: list[str],
                          allowed_optional_sections: list[str],
                          allowed_section_order: list[str]) -> str:
    payload = {
        "policy_id": "gen04-extractive-v1",
        "template_id": template_id,
        "document_type": document_type.value,
        "required_sections": required_sections,
        "allowed_optional_sections": allowed_optional_sections,
        "allowed_section_order": allowed_section_order,
    }
    return compute_sha256_digest(payload)


CONTENT_REQUIREMENTS_POLICIES: dict[tuple[str, DocumentType], ValidationContentRequirements] = {}


def _init_content_requirements() -> None:
    specs = [
        ("content-basic", DocumentType.CV, ["experience"], ["summary", "education", "skills"], ["summary", "experience", "education", "skills"]),
        ("content-compact", DocumentType.CV, ["experience"], ["skills"], ["experience", "skills"]),
        ("content-basic", DocumentType.COVER_LETTER, ["experience", "closing"], ["opening", "motivation"], ["opening", "experience", "motivation", "closing"]),
        ("content-compact", DocumentType.COVER_LETTER, ["experience", "closing"], [], ["experience", "closing"]),
    ]
    for tid, dtype, req, opt, order in specs:
        digest = compute_policy_digest(tid, dtype, req, opt, order)
        CONTENT_REQUIREMENTS_POLICIES[(tid, dtype)] = ValidationContentRequirements(
            policy_id="gen04-extractive-v1",
            template_id=tid,
            document_type=dtype,
            required_sections=req,
            allowed_optional_sections=opt,
            allowed_section_order=order,
            policy_digest=digest,
        )


_init_content_requirements()


def get_content_requirements(template_id: str, document_type: DocumentType) -> ValidationContentRequirements | None:
    return CONTENT_REQUIREMENTS_POLICIES.get((template_id, document_type))


class DocumentValidationIssue(ContractModel):
    """Detailed factual or structural finding with full traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    issue_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    severity: Literal["fatal", "warning"]
    message: str = Field(min_length=1, max_length=4000)
    document_path: str | None = None
    section_id: str | None = None
    entry_id: str | None = None
    claim_id: str | None = None
    block_id: str | None = None
    evidence_reference: EvidenceReference | None = None
    source_field: str | None = None
    inherited_from: str | None = None
    review_reason: str | None = None
    suggested_action: str | None = None
    requires_human_review: Literal[True] = True


class RuleOutcome(ContractModel):
    """Outcome of evaluating a single validation rule."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    rule_id: str
    status: Literal["checked", "not_applicable", "not_checked"]
    reason: str | None = None


class DocumentValidationReport(ContractModel):
    """Immutable durable report from GEN-04 validation."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    draft_id: uuid.UUID
    validated_draft_hash: str
    input_binding: ValidationInputBinding
    validator_version: str
    rule_set_id: str
    rule_outcomes: dict[str, RuleOutcome]
    issues: list[DocumentValidationIssue] = Field(default_factory=list)
    fatal_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    evaluation_status: Literal["complete", "incomplete"]
    render_decision: Literal["blocked", "allowed_for_review"]
    requires_human_review: Literal[True] = True
    semantic_limits_notice: str = Field(default=SEMANTIC_LIMITS_NOTICE, min_length=1, max_length=4000)
    completed_at: datetime
    report_hash: str

    @model_validator(mode="after")
    def validate_report_invariants(self):
        actual_fatal = sum(1 for i in self.issues if i.severity == "fatal")
        actual_warning = sum(1 for i in self.issues if i.severity == "warning")
        if self.fatal_count != actual_fatal:
            raise ValueError(f"fatal_count mismatch: {self.fatal_count} vs {actual_fatal}")
        if self.warning_count != actual_warning:
            raise ValueError(f"warning_count mismatch: {self.warning_count} vs {actual_warning}")

        if self.render_decision == "allowed_for_review":
            if self.evaluation_status != "complete":
                raise ValueError("Cannot allow rendering with incomplete evaluation status")
            if self.fatal_count > 0:
                raise ValueError("Cannot allow rendering when fatal errors exist")
            if any(r.status == "not_checked" for r in self.rule_outcomes.values()):
                raise ValueError("Cannot allow rendering when rules remain not_checked")
        return self


def compute_report_hash(report_data: dict[str, Any]) -> str:
    """Compute sha256 hash of report dictionary excluding report_hash field."""
    filtered = {k: v for k, v in report_data.items() if k != "report_hash"}
    return compute_sha256_digest(filtered)


class DocumentValidationSettings(ContractModel):
    """Configuration and rule set settings for GEN-04 validation."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    rule_set_id: Literal["gen04-extractive-v1"] = "gen04-extractive-v1"
    rule_set_version: str = "1.0.0"
    max_issues: int = Field(default=200, gt=0)
    fail_on_first_fatal: bool = False
    allowed_content_schema_versions: list[str] = Field(default_factory=lambda: ["2.0"])

    @property
    def rule_set_digest(self) -> str:
        return compute_sha256_digest({
            "rule_set_id": self.rule_set_id,
            "rule_set_version": self.rule_set_version,
            "allowed_content_schema_versions": self.allowed_content_schema_versions,
        })


class ValidatedDraftForRendering(ContractModel):
    """Immutable envelope granting rendering authorization for review."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    draft: DraftDocumentV2
    draft_hash: str
    report_id: uuid.UUID
    report_hash: str
    binding_hash: str
    content_spec_id: str
    render_decision: Literal["allowed_for_review"] = "allowed_for_review"
    requires_human_review: Literal[True] = True
    review_warnings: list[DocumentValidationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_fatal_warnings(self):
        if any(w.severity == "fatal" for w in self.review_warnings):
            raise ValueError("ValidatedDraftForRendering cannot contain fatal issues")
        return self


class ValidationRunResult(ContractModel):
    """Outcome of running validation."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    report: DocumentValidationReport | None = None
    error: ClassifiedError | None = None
