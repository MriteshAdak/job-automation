"""Domain models for unapproved drafts, provenance, inclusion views, and history.

Keeps draft proposals strictly distinct from approved immutable C01 ProfileSnapshots.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal

from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate, UtcDatetime
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
)

SUPPORTED_PURPOSES: frozenset[str] = frozenset({"assessment", "cv", "cover_letter"})
DEFAULT_RULE_VERSION: str = "1.0"


class ProvenanceRecord(ContractModel):
    """Metadata recording provenance of candidate evidence or attestations."""

    provenance_id: str = Field(min_length=1, description="Stable identifier for this provenance entry")
    candidate_id: uuid.UUID = Field(description="UUID of the owning candidate")
    source_type: Literal["document", "attestation", "import"] = Field(
        description="Type of evidence source",
    )
    locator: str = Field(
        min_length=1,
        description="Human-readable locator, section, page, or reference",
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of original evidence bytes if file-backed",
    )
    file_path: str | None = Field(
        default=None,
        description="Relative path beneath profiles_dir if stored",
    )
    captured_at: UtcDatetime = Field(description="UTC timestamp when provenance was captured")
    notes: str | None = Field(default=None, description="Optional notes on provenance")


class DraftFact(ContractModel):
    """Unapproved proposal for a candidate fact."""

    fact_id: uuid.UUID = Field(description="Stable UUID for this candidate fact")
    kind: EvidenceFactKind = Field(description="Category of evidence fact")
    parent_id: uuid.UUID | None = Field(
        default=None,
        description="Parent role or project ID if hierarchical",
    )
    title: str = Field(min_length=1, description="Fact headline (e.g. role title or degree)")
    organization: str | None = Field(
        default=None,
        description="Employer, institution, or client organization",
    )
    start_date: PrecisionDate | None = Field(
        default=None,
        description="Start date with explicit precision",
    )
    end_date: PrecisionDate | None = Field(
        default=None,
        description="End date with explicit precision; null if unknown or ongoing",
    )
    is_ongoing: bool = Field(
        default=False,
        description="Explicit flag indicating ongoing employment/project (distinct from unknown end date)",
    )
    claims: list[str] = Field(
        default_factory=list,
        description="Specific factual claims / accomplishments",
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Demonstrated skills / technologies",
    )
    metrics: list[str] = Field(
        default_factory=list,
        description="Verified quantitative metrics / achievements",
    )
    provenance_id: str | None = Field(
        default=None,
        description="Reference to ProvenanceRecord.provenance_id if present",
    )
    provenance_summary: str = Field(
        default="",
        description="Human-readable provenance summary or reference text",
    )
    allowed_uses: list[str] = Field(
        default_factory=list,
        description="Explicitly permitted contexts (cv, cover_letter, assessment); empty means no downstream use",
    )


class DraftProfile(ContractModel):
    """Working unapproved candidate profile proposal."""

    draft_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique UUID for this draft")
    candidate_id: uuid.UUID = Field(description="Owning candidate UUID")
    base_profile_version: str | None = Field(
        default=None,
        description="Version string of approved snapshot this draft is based on, if any",
    )
    proposed_eligibility: CandidateEligibility = Field(
        description="Candidate eligibility facts under review",
    )
    facts: list[DraftFact] = Field(
        default_factory=list,
        description="List of proposed candidate facts",
    )
    provenance_records: list[ProvenanceRecord] = Field(
        default_factory=list,
        description="Provenance records attached to this draft",
    )
    notes: str | None = Field(default=None, description="Draft notes or change summary")
    created_at: UtcDatetime = Field(description="UTC timestamp of draft creation")
    updated_at: UtcDatetime = Field(description="UTC timestamp of last draft update")
    content_digest: str = Field(
        default="",
        description="Deterministic content hash of facts and eligibility (set by compute_digest)",
    )

    @model_validator(mode="after")
    def _compute_digest_if_empty(self) -> DraftProfile:
        if not self.content_digest:
            object.__setattr__(self, "content_digest", self.compute_digest())
        return self

    def compute_digest(self) -> str:
        """Compute deterministic SHA-256 digest of reviewable content."""
        payload = {
            "candidate_id": str(self.candidate_id),
            "base_profile_version": self.base_profile_version,
            "eligibility": self.proposed_eligibility.model_dump(mode="json"),
            "facts": [
                {
                    "fact_id": str(f.fact_id),
                    "kind": f.kind.value,
                    "parent_id": str(f.parent_id) if f.parent_id else None,
                    "title": f.title,
                    "organization": f.organization,
                    "start_date": f.start_date.model_dump(mode="json") if f.start_date else None,
                    "end_date": f.end_date.model_dump(mode="json") if f.end_date else None,
                    "is_ongoing": f.is_ongoing,
                    "claims": sorted(f.claims),
                    "skills": sorted(f.skills),
                    "metrics": sorted(f.metrics),
                    "provenance_id": f.provenance_id,
                    "provenance_summary": f.provenance_summary,
                    "allowed_uses": sorted(f.allowed_uses),
                }
                for f in sorted(self.facts, key=lambda x: str(x.fact_id))
            ],
            "notes": self.notes,
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ProfileVersionRecord(ContractModel):
    """Metadata for an approved published snapshot in the version ledger."""

    profile_version: str = Field(description="Published version string (e.g. 'v1', 'v2')")
    candidate_id: uuid.UUID = Field(description="Owning candidate UUID")
    version_sequence: int = Field(ge=1, description="Monotonically increasing sequence number")
    predecessor_version: str | None = Field(
        default=None,
        description="Previous version string, or None if first version",
    )
    is_current: bool = Field(default=False, description="Whether this version is the current pointer")
    approved_by: str = Field(min_length=1, description="Approver identifier")
    approved_at: UtcDatetime = Field(description="UTC timestamp of approval")
    notes: str | None = Field(default=None, description="Approval notes or change summary")
    content_hash: str = Field(description="SHA-256 hash of published snapshot JSON")
    created_at: UtcDatetime = Field(description="UTC timestamp of record creation")


class ProfileInclusionView(ContractModel):
    """Purpose-filtered view of candidate evidence for downstream consumers (JSON/RAG)."""

    profile_version: str = Field(description="Snapshot version from which this view was derived")
    candidate_id: uuid.UUID = Field(description="Candidate UUID")
    purpose: str = Field(description="Intended downstream purpose (cv, cover_letter, assessment)")
    rule_version: str = Field(default=DEFAULT_RULE_VERSION, description="Version of inclusion rules applied")
    eligible_facts: list[CandidateFact] = Field(
        default_factory=list,
        description="Filtered eligible facts in deterministic order",
    )
    eligible_fact_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="List of eligible fact UUIDs",
    )
    mandatory_facts: list[CandidateFact] = Field(
        default_factory=list,
        description="Facts deemed mandatory (e.g. chronological anchor)",
    )
    explicit_eligibility: CandidateEligibility = Field(
        description="Confirmed candidate eligibility",
    )
    excluded_fact_count: int = Field(
        default=0,
        description="Count of facts excluded due to permission restrictions",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings regarding restricted optional context",
    )


class FactDiff(ContractModel):
    """Differences observed for a single fact between two versions."""

    fact_id: uuid.UUID
    change_type: Literal["added", "removed", "updated"]
    title: str
    changed_fields: list[str] = Field(default_factory=list)


class ProfileDiff(ContractModel):
    """Structural difference between two approved profile versions."""

    base_version: str
    target_version: str
    added_facts: list[CandidateFact] = Field(default_factory=list)
    removed_facts: list[CandidateFact] = Field(default_factory=list)
    updated_facts: list[FactDiff] = Field(default_factory=list)
    unchanged_fact_ids: list[uuid.UUID] = Field(default_factory=list)
    eligibility_changed: bool = False
