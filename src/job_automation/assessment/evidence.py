"""Traceable evidence builders for job postings and candidate facts (C08)."""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
    SourceSpan,
)
from job_automation.contracts.postings import NormalizedPosting


def build_job_evidence(
    posting: NormalizedPosting,
    posting_revision: str,
    field_path: str,
    quotation: str | None = None,
    span: tuple[int, int] | None = None,
) -> JobEvidenceReference | None:
    """Build a C08 JobEvidenceReference strictly citing existing posting content.

    Returns None if neither a quotation nor span can be provided.
    Never fabricates a quotation for missing or absent information.
    """
    source_span: SourceSpan | None = None
    if span is not None:
        start, end = span
        if end > start and start >= 0:
            source_span = SourceSpan(start=start, end=end)

    if quotation is None and source_span is None:
        return None

    # Truncate overly long quotations to a reasonable snippet length while preserving meaning
    if quotation and len(quotation) > 300:
        quotation = quotation[:297] + "..."

    return JobEvidenceReference(
        posting_revision=posting_revision,
        field_path=field_path,
        quotation=quotation,
        source_span=source_span,
    )


def build_candidate_evidence(
    profile_version: str,
    fact_id: uuid.UUID,
) -> CandidateEvidenceReference:
    """Build a C08 CandidateEvidenceReference citing an approved candidate fact."""
    return CandidateEvidenceReference(
        profile_version=profile_version,
        fact_id=fact_id,
    )

