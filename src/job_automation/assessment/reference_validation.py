"""Exact citation resolution and evidence reference validation (MATCH-02-S04).

Enforces:
- Exact Unicode character offsets for job spans
- Verbatim quotation matching without fuzzy matching or ellipses
- Candidate facts must exist in the approved profile AND be present in the admitted context bundle
- Restricted/private candidate facts cannot be cited
"""

from __future__ import annotations

import uuid

from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
)
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import ProfileSnapshot


def validate_job_reference(
    ref: JobEvidenceReference,
    posting: NormalizedPosting,
    posting_revision: str,
    context_prefix: str = "Job evidence",
) -> list[ValidationIssue]:
    """Validate a JobEvidenceReference against the exact normalized posting.

    Checks:
    1. Posting revision matches target revision
    2. Field path resolves to a valid posting text field
    3. Source span is within Unicode bounds (0 <= start < end <= len)
    4. Quotation is an exact substring of the field
    5. Span text and quotation agree exactly
    """
    issues: list[ValidationIssue] = []

    # 1. Revision match
    if ref.posting_revision != posting_revision:
        issues.append(
            ValidationIssue(
                field_path="posting_revision",
                code="revision_mismatch",
                message=f"{context_prefix} cites revision '{ref.posting_revision}', expected '{posting_revision}'",
            )
        )

    # 2. Field path resolution
    field_text: str | None = None
    if ref.field_path == "description_clean":
        field_text = posting.description_clean
    elif ref.field_path == "title":
        field_text = posting.title
    elif ref.field_path == "company_name_hint":
        field_text = posting.company_name_hint
    else:
        val = getattr(posting, ref.field_path, None)
        if isinstance(val, str):
            field_text = val

    if field_text is None:
        issues.append(
            ValidationIssue(
                field_path=ref.field_path,
                code="invalid_field_path",
                message=f"{context_prefix} field path '{ref.field_path}' does not resolve to a valid text field",
            )
        )
        return issues

    # 3. Source span validation
    span = ref.source_span
    if span is not None:
        if span.start < 0 or span.end > len(field_text) or span.start >= span.end:
            issues.append(
                ValidationIssue(
                    field_path="source_span",
                    code="out_of_bounds_span",
                    message=f"{context_prefix} span ({span.start}, {span.end}) is out of bounds for field of length {len(field_text)}",
                )
            )

    # 4. Quotation validation
    quote = ref.quotation
    if quote is not None:
        if not quote:
            issues.append(
                ValidationIssue(
                    field_path="quotation",
                    code="empty_quotation",
                    message=f"{context_prefix} quotation cannot be empty",
                )
            )
        elif quote not in field_text:
            issues.append(
                ValidationIssue(
                    field_path="quotation",
                    code="quotation_not_found",
                    message=f"{context_prefix} quotation does not exist as an exact substring in '{ref.field_path}'",
                )
            )

    # 5. Span and quotation agreement
    if span is not None and quote is not None and 0 <= span.start < span.end <= len(field_text):
        span_slice = field_text[span.start:span.end]
        if span_slice != quote:
            issues.append(
                ValidationIssue(
                    field_path="quotation",
                    code="quote_span_mismatch",
                    message=f"{context_prefix} quotation does not match source span text: '{quote[:30]}' vs '{span_slice[:30]}'",
                )
            )

    return issues


def validate_candidate_reference(
    ref: CandidateEvidenceReference,
    profile: ProfileSnapshot,
    bundle: ContextBundle,
    context_prefix: str = "Candidate evidence",
) -> list[ValidationIssue]:
    """Validate a CandidateEvidenceReference against candidate snapshot and admitted context bundle.

    Checks:
    1. Profile version matches
    2. Fact UUID exists in approved profile snapshot
    3. Fact UUID was admitted into the C09 ContextBundle selected for the model
    4. Fact is not restricted/private for purpose='assessment'
    """
    issues: list[ValidationIssue] = []

    # 1. Profile version check
    if ref.profile_version != profile.profile_version:
        issues.append(
            ValidationIssue(
                field_path="profile_version",
                code="profile_version_mismatch",
                message=f"{context_prefix} cites profile version '{ref.profile_version}', expected '{profile.profile_version}'",
            )
        )

    # 2. Fact existence in profile
    fact_map = {f.fact_id: f for f in profile.evidence_records}
    fact = fact_map.get(ref.fact_id)

    if fact is None:
        issues.append(
            ValidationIssue(
                field_path="fact_id",
                code="unknown_candidate_fact_id",
                message=f"{context_prefix} cites fact UUID '{ref.fact_id}' not found in profile snapshot",
            )
        )
        return issues

    # 3. Fact admission in model context bundle
    # A fact that exists in snapshot but was omitted or not retrieved is NOT valid model evidence!
    admitted_ids = set(bundle.selected_fact_ids)
    if ref.fact_id not in admitted_ids:
        issues.append(
            ValidationIssue(
                field_path="fact_id",
                code="unselected_fact_reference",
                message=f"{context_prefix} cites fact UUID '{ref.fact_id}' which was not admitted into the model context bundle",
            )
        )

    # 4. Check fact permission (must be allowed for purpose='assessment')
    if hasattr(fact, "allowed_uses") and "assessment" not in fact.allowed_uses:
        issues.append(
            ValidationIssue(
                field_path="fact_id",
                code="restricted_fact_reference",
                message=f"{context_prefix} cites fact UUID '{ref.fact_id}' which is not permitted for assessment use",
            )
        )

    return issues
