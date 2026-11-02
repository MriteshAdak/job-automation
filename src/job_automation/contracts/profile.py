"""C01 ProfileSnapshot contracts.

Represents candidate truth: approved evidence records, explicit eligibility facts,
and approval metadata. Both JSON and RAG context strategies consume this same snapshot.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate, UtcDatetime


class ProfileApprovalMetadata(ContractModel):
    """Metadata recording human approval of the candidate profile."""

    is_approved: bool = Field(description="Whether this profile snapshot is approved for use")
    approved_by: str = Field(min_length=1, description="Identity of the approver (candidate)")
    approved_at: UtcDatetime = Field(description="UTC timestamp of approval")
    notes: str | None = Field(default=None, description="Optional approval notes or version summary")


class CandidateEligibility(ContractModel):
    """Explicit eligibility facts confirmed by the candidate.

    Distinct from desired job preferences. An absent proficiency is unknown,
    not absent capability.
    """

    work_authorization_countries: list[str] = Field(
        default_factory=list,
        description="ISO 3166-1 alpha-2 country codes where candidate is authorized to work",
    )
    target_locations: list[str] = Field(
        default_factory=list,
        description="Locations candidate is eligible/willing to work in",
    )
    remote_eligible: bool = Field(
        default=True,
        description="Whether candidate is eligible for remote work",
    )
    min_salary: MoneyAmount | None = Field(
        default=None,
        description="Minimum acceptable compensation; null means unspecified/unknown",
    )
    language_proficiencies: dict[str, str] = Field(
        default_factory=dict,
        description="Language codes (e.g. 'de', 'en') mapped to CEFR levels (e.g. 'C1', 'B2') or descriptions",
    )


class CandidateFact(ContractModel):
    """Individual approved evidence record.

    Traced to specific parent roles/projects, dated with explicit precision,
    and tagged with allowed uses (e.g. cv, cover_letter, assessment).
    """

    fact_id: uuid.UUID = Field(description="Unique ID for this candidate fact")
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
        description="End date with explicit precision; null if ongoing/present",
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
    provenance: str = Field(
        min_length=1,
        description="Source reference (e.g. 'contract-2023', 'cv_v2_import')",
    )
    allowed_uses: list[str] = Field(
        default_factory=lambda: ["cv", "cover_letter", "assessment"],
        description="Permitted contexts for this fact",
    )


class ProfileSnapshot(ContractModel):
    """C01 Candidate Profile Snapshot.

    Immutable snapshot of candidate facts and explicit eligibility.
    Both context strategies consume this exact approved snapshot.
    """

    candidate_id: uuid.UUID = Field(description="Persistent candidate UUID")
    profile_version: str = Field(min_length=1, description="Version string for this snapshot")
    approval_metadata: ProfileApprovalMetadata
    explicit_eligibility: CandidateEligibility
    evidence_records: list[CandidateFact] = Field(
        default_factory=list,
        description="List of approved candidate evidence facts",
    )

