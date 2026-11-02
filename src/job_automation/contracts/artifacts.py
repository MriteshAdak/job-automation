"""C14 DraftDocument and Artifact contracts.

Structured document content with typed evidence references (candidate or job/employer),
and local/delivered file artifact records. Separates artifact delivery from candidate approval.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.contracts.evidence import EvidenceReference
from job_automation.contracts.generation import FrozenInputVersions
from job_automation.contracts.primitives import ContentHash, UtcDatetime


class DocumentClaim(ContractModel):
    """Factual claim in a generated draft grounded in explicit evidence.

    Cites candidate facts for candidate claims, or job postings for employer/job claims.
    """

    claim_id: str = Field(min_length=1, description="Identifier for this claim within the document")
    text: str = Field(min_length=1, description="Claim text appearing in the draft")
    evidence_reference: EvidenceReference = Field(
        description="Traceable reference to approved candidate fact or posting text"
    )


class SubjectiveSection(ContractModel):
    """Subjective, motivational, or narrative section requiring human review."""

    section_title: str = Field(min_length=1, description="Section heading (e.g. 'Motivation')")
    text: str = Field(min_length=1, description="Generated subjective content")
    requires_human_review: bool = Field(
        default=True,
        description="Always requires explicit human review; never self-approves",
    )
    review_notes: str | None = Field(
        default=None,
        description="Reviewer notes or guidance",
    )


class DraftDocument(ContractModel):
    """C14 Draft Document Content.

    Structured sections and factual claims before rendering into physical files.
    """

    request_id: uuid.UUID = Field(description="Parent GenerationRequest UUID")
    document_type: DocumentType = Field(description="cv or cover_letter")
    document_version: str = Field(min_length=1, description="Version string for this draft")
    title: str = Field(min_length=1, description="Document title")
    candidate_name: str = Field(min_length=1, description="Candidate name")
    target_role: str = Field(min_length=1, description="Target job title")
    target_company: str = Field(min_length=1, description="Target employer name")
    structured_claims: list[DocumentClaim] = Field(
        default_factory=list,
        description="Factual claims with typed evidence references",
    )
    subjective_sections: list[SubjectiveSection] = Field(
        default_factory=list,
        description="Subjective or narrative sections flagged for human review",
    )
    frozen_inputs: FrozenInputVersions = Field(
        description="Frozen input snapshots used for this generation"
    )
    model_call_ref: uuid.UUID | None = Field(
        default=None,
        description="UUID linking to the ModelCall that generated this content",
    )
    review_warnings: list[str] = Field(
        default_factory=list,
        description="Warnings regarding subjective paraphrasing or ungrounded statements",
    )


class Artifact(ContractModel):
    """C14 Physical Artifact.

    Represents a rendered file (DOCX or PDF) stored locally and optionally delivered
    to Salesforce Files. Separates delivery status from candidate human approval.
    """

    artifact_id: uuid.UUID = Field(description="Unique artifact UUID")
    request_id: uuid.UUID = Field(description="Parent GenerationRequest UUID")
    artifact_version: int = Field(ge=1, default=1, description="Sequential artifact version")
    format: Literal["docx", "pdf"] = Field(description="File format: docx or pdf")
    local_path: str = Field(min_length=1, description="Absolute local filesystem path to artifact")
    content_hash: ContentHash = Field(description="SHA-256 hash of the rendered file")
    size_bytes: int = Field(ge=0, description="Size in bytes")
    remote_file_id: str | None = Field(
        default=None,
        description="Salesforce ContentVersion or ContentDocument ID once delivered",
    )
    delivery_status: Literal["local_only", "upload_pending", "delivered"] = Field(
        default="local_only",
        description="Remote delivery state",
    )
    approval_status: DocumentApproval = Field(
        default=DocumentApproval.DRAFT,
        description="Human approval status: draft, approved, or superseded",
    )
    reconciliation_marker: str | None = Field(
        default=None,
        description="Unique idempotency marker for safe Salesforce upload reconciliation",
    )
    created_at: UtcDatetime = Field(description="Artifact creation timestamp (UTC)")

