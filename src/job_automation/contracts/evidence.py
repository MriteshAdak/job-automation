"""C08 EvidenceReference contracts.

Discriminated union for traceable claims:
- Candidate claims require profile_version and fact_id.
- Job/employer claims require posting_revision, field_path, and supporting quotation or source span.
A valid reference proves traceability, not semantic correctness.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel


class SourceSpan(ContractModel):
    """Character offsets within a source field."""

    start: int = Field(ge=0, description="0-based start character index")
    end: int = Field(gt=0, description="0-based end character index (exclusive)")

    @model_validator(mode="after")
    def _validate_range(self) -> SourceSpan:
        if self.end <= self.start:
            raise ValueError(
                f"Span end ({self.end}) must be greater than start ({self.start})"
            )
        return self


class CandidateEvidenceReference(ContractModel):
    """Reference citing an approved candidate profile fact."""

    source_kind: Literal["candidate"] = "candidate"
    profile_version: str = Field(min_length=1, description="Version of the profile snapshot")
    fact_id: uuid.UUID = Field(description="UUID of the cited candidate fact")


class JobEvidenceReference(ContractModel):
    """Reference citing a specific job posting requirement or statement."""

    source_kind: Literal["job"] = "job"
    posting_revision: str = Field(
        min_length=1, description="Content hash or revision ID of the posting"
    )
    field_path: str = Field(
        min_length=1, description="Path to the cited field (e.g. 'description', 'requirements')"
    )
    quotation: str | None = Field(
        default=None, description="Direct supporting quotation from the source text"
    )
    source_span: SourceSpan | None = Field(
        default=None, description="Character offsets of the cited passage in the field"
    )

    @model_validator(mode="after")
    def _validate_evidence_present(self) -> JobEvidenceReference:
        if self.quotation is None and self.source_span is None:
            raise ValueError(
                "Job evidence reference must provide at least one of 'quotation' or 'source_span'"
            )
        return self


# Discriminated union for evidence references
EvidenceReference = Annotated[
    Union[CandidateEvidenceReference, JobEvidenceReference],
    Field(discriminator="source_kind"),
]

