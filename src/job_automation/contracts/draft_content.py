"""C14 v2 content. Evidence traceability is not proof of semantic truth."""
from __future__ import annotations

import json
import uuid
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import DocumentType
from job_automation.contracts.evidence import EvidenceReference
from job_automation.contracts.generation import FrozenInputVersions
from job_automation.contracts.primitives import PrecisionDate

Text = Annotated[str, Field(min_length=1, max_length=4000)]
LocalId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]


class ContentRecord(ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True, strict=True)
    schema_version: Literal["1.0"] = "1.0"


class DraftClaim(ContentRecord):
    claim_id: LocalId
    claim_subject: Literal["candidate", "job"]
    text: Text
    evidence_reference: EvidenceReference
    source_field: Literal["title", "organization", "start_date", "end_date", "skills", "metrics", "claims", "description_clean", "company_name_hint"]
    source_index: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def subject_agrees(self):
        if self.claim_subject != self.evidence_reference.source_kind:
            raise ValueError("Claim subject and evidence kind disagree")
        if self.evidence_reference.schema_version != "1.0":
            raise ValueError("Unsupported C08 version")
        return self


class SubjectiveBlock(ContentRecord):
    block_id: LocalId
    text: Text
    requires_human_review: Literal[True] = True


class DraftEntry(ContentRecord):
    """Ordered role/education entry or letter paragraph containing atomic claims."""
    entry_id: LocalId
    claim_ids: list[LocalId] = Field(default_factory=list, max_length=100)
    subjective_ids: list[LocalId] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def not_empty(self):
        if not self.claim_ids and not self.subjective_ids:
            raise ValueError("Empty content entry")
        return self


class DraftSection(ContentRecord):
    section_id: LocalId
    heading_key: Literal["summary", "experience", "education", "skills", "motivation", "opening", "closing"]
    claim_ids: list[LocalId] = Field(default_factory=list, max_length=100)
    subjective_ids: list[LocalId] = Field(default_factory=list, max_length=20)
    entries: list[DraftEntry] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def not_empty(self):
        if not self.claim_ids and not self.subjective_ids and not self.entries:
            raise ValueError("Empty content section")
        return self


class DraftReviewIssue(ContentRecord):
    code: LocalId
    message: Text
    severity: Literal["warning", "info"] = "warning"
    uncertainty_kind: Literal["semantic_review", "source_unknown", "source_uncertainty", "subjective", "translation", "upstream"]
    affected_ids: list[LocalId] = Field(default_factory=list, max_length=200)
    source_references: list[EvidenceReference] = Field(default_factory=list, max_length=100)
    requires_human_review: Literal[True] = True
    upstream_warning: Text | None = None


class DraftContentProposal(ContentRecord):
    """No request identity, approval, paths, headings with hidden facts, or tools."""
    sections: list[DraftSection] = Field(min_length=1, max_length=12)
    claims: list[DraftClaim] = Field(min_length=1, max_length=100)
    subjective_blocks: list[SubjectiveBlock] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def coherent_links(self):
        ids = ([s.section_id for s in self.sections] + [e.entry_id for s in self.sections for e in s.entries]
               + [c.claim_id for c in self.claims] + [b.block_id for b in self.subjective_blocks])
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate content ID")
        linked_claims = [i for s in self.sections for i in s.claim_ids] + [i for s in self.sections for e in s.entries for i in e.claim_ids]
        linked_blocks = [i for s in self.sections for i in s.subjective_ids] + [i for s in self.sections for e in s.entries for i in e.subjective_ids]
        if sorted(linked_claims) != sorted(c.claim_id for c in self.claims):
            raise ValueError("Every claim must occur exactly once in sections")
        if sorted(linked_blocks) != sorted(b.block_id for b in self.subjective_blocks):
            raise ValueError("Every subjective block must occur exactly once in sections")
        return self


class ProtectedSourceValue(ContentRecord):
    claim_id: LocalId
    source_field: str
    original_value: str | list[str] | PrecisionDate | None
    evidence_reference: EvidenceReference


class DraftProvenance(ContentRecord):
    seal_id: str
    seal_hash: str
    binding_hash: str
    context_receipt_id: uuid.UUID
    context_hash: str
    recipe_hash: str
    prompt_version: str
    schema_id: str
    schema_digest: str
    input_fingerprint: str
    model_identifier: str
    model_digest: str
    model_call_ref: uuid.UUID
    receipt_id: uuid.UUID


class DraftDocumentV2(DraftContentProposal):
    schema_version: Literal["2.0"] = "2.0"
    draft_id: uuid.UUID
    request_id: uuid.UUID
    document_type: DocumentType
    document_version: str
    target_language: Literal["de", "en"]
    template_id: str
    template_version: str
    template_content_digest: str
    headings: dict[str, str]
    candidate_name: None = None
    protected_values: list[ProtectedSourceValue]
    review_issues: list[DraftReviewIssue]
    requires_human_review: Literal[True] = True
    validation_status: Literal["pending_gen04"] = "pending_gen04"
    frozen_inputs: FrozenInputVersions
    provenance: DraftProvenance

    @model_validator(mode="after")
    def complete_source_links(self):
        claims = {c.claim_id: c for c in self.claims}
        if set(self.headings) != {s.section_id for s in self.sections}:
            raise ValueError("Every section requires one localized heading")
        if sorted(v.claim_id for v in self.protected_values) != sorted(claims):
            raise ValueError("Every claim requires one protected source value")
        for value in self.protected_values:
            claim = claims[value.claim_id]
            if value.evidence_reference != claim.evidence_reference or value.source_field != claim.source_field:
                raise ValueError("Protected value and claim source disagree")
        ids = set(claims) | {s.section_id for s in self.sections} | {b.block_id for b in self.subjective_blocks} | {e.entry_id for s in self.sections for e in s.entries}
        if any(i not in ids for issue in self.review_issues for i in issue.affected_ids):
            raise ValueError("Review issue has a dangling location")
        return self


def read_draft_json(payload: str):
    """Explicit legacy reader; unsupported versions never silently downcast."""
    from job_automation.contracts.artifacts import DraftDocument
    version = json.loads(payload).get("schema_version", "1.0")
    if version == "1.0":
        return DraftDocument.model_validate_json(payload)
    if version == "2.0":
        return DraftDocumentV2.model_validate_json(payload)
    raise ValueError("Unsupported C14 content version")
