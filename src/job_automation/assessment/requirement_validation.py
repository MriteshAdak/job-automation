"""Validation of extracted job requirements against posting text (MATCH-02-S02)."""

from __future__ import annotations

import re
from typing import Any

from job_automation.assessment.llm_records import (
    RequirementItem,
    RequirementIssue,
    RequirementObligation,
    RequirementSet,
)
from job_automation.contracts.postings import NormalizedPosting


def validate_requirement_item(
    item: RequirementItem,
    posting: NormalizedPosting,
    posting_revision: str,
) -> list[RequirementIssue]:
    """Validate a single requirement's source citations and semantic consistency."""
    issues: list[RequirementIssue] = []
    job_ev = item.job_evidence

    # 1. Posting revision check
    if job_ev.posting_revision != posting_revision:
        issues.append(
            RequirementIssue(
                code="revision_mismatch",
                stage="requirement_validation",
                requirement_id=item.requirement_id,
                message=f"Job evidence revision '{job_ev.posting_revision}' does not match target revision '{posting_revision}'",
                severity="error",
            )
        )

    # 2. Field path check
    field_text: str | None = None
    if job_ev.field_path == "description_clean":
        field_text = posting.description_clean
    elif job_ev.field_path == "title":
        field_text = posting.title
    elif job_ev.field_path == "company_name_hint":
        field_text = posting.company_name_hint
    else:
        # Check if attribute exists on posting
        val = getattr(posting, job_ev.field_path, None)
        if isinstance(val, str):
            field_text = val

    if field_text is None:
        issues.append(
            RequirementIssue(
                code="invalid_field_path",
                stage="requirement_validation",
                requirement_id=item.requirement_id,
                message=f"Field path '{job_ev.field_path}' does not resolve to a text field on NormalizedPosting",
                severity="error",
            )
        )
        return issues

    # 3. Source span validation
    span = job_ev.source_span
    if span is not None:
        if span.start < 0 or span.end > len(field_text) or span.start >= span.end:
            issues.append(
                RequirementIssue(
                    code="invalid_source_span",
                    stage="requirement_validation",
                    requirement_id=item.requirement_id,
                    message=f"Source span ({span.start}, {span.end}) is out of bounds for field of length {len(field_text)}",
                    severity="error",
                )
            )

    # 4. Quotation text validation
    quote = job_ev.quotation
    if quote is not None:
        if not quote:
            issues.append(
                RequirementIssue(
                    code="empty_quotation",
                    stage="requirement_validation",
                    requirement_id=item.requirement_id,
                    message="Quotation text cannot be empty",
                    severity="error",
                )
            )
        elif quote not in field_text:
            issues.append(
                RequirementIssue(
                    code="quotation_not_found",
                    stage="requirement_validation",
                    requirement_id=item.requirement_id,
                    message=f"Quotation '{quote[:50]}' does not appear as an exact substring in '{job_ev.field_path}'",
                    severity="error",
                )
            )

    # 5. Span and quotation agreement
    if span is not None and quote is not None and span.end <= len(field_text) and span.start >= 0:
        actual_span_text = field_text[span.start:span.end]
        if actual_span_text != quote:
            issues.append(
                RequirementIssue(
                    code="quote_span_mismatch",
                    stage="requirement_validation",
                    requirement_id=item.requirement_id,
                    message=f"Span text does not match quotation: '{actual_span_text[:30]}' vs '{quote[:30]}'",
                    severity="error",
                )
            )

    # 6. Semantic entailment check for mechanically detectable hallucinations
    # If the requirement claims 5 years experience, but the quote does not contain '5'
    if item.threshold is not None:
        if quote is not None and item.threshold not in quote:
            issues.append(
                RequirementIssue(
                    code="unsupported_requirement_extraction",
                    stage="requirement_validation",
                    requirement_id=item.requirement_id,
                    message=f"Requirement claims threshold '{item.threshold}' which does not appear in cited quotation",
                    severity="warning",
                )
            )

    # If requirement claims 'required' but quote has explicit negation
    if quote is not None:
        quote_lower = quote.lower()
        if item.obligation == RequirementObligation.REQUIRED:
            if (
                "keine zertifizierung erforderlich" in quote_lower
                or "no degree required" in quote_lower
                or "nicht erforderlich" in quote_lower
                or "not required" in quote_lower
                or "optional" in quote_lower
            ):
                issues.append(
                    RequirementIssue(
                        code="unsupported_requirement_extraction",
                        stage="requirement_validation",
                        requirement_id=item.requirement_id,
                        message=f"Requirement marked REQUIRED contradicts negation in quote: '{quote[:50]}'",
                        severity="warning",
                    )
                )

    return issues


def validate_requirement_set(
    req_set: RequirementSet,
    posting: NormalizedPosting,
    posting_revision: str,
) -> list[RequirementIssue]:
    """Validate all requirements in a RequirementSet and check for duplicates."""
    all_issues: list[RequirementIssue] = list(req_set.issues)
    seen_ids: set[str] = set()

    for item in req_set.requirements:
        if item.requirement_id in seen_ids:
            all_issues.append(
                RequirementIssue(
                    code="duplicate_requirement_id",
                    stage="requirement_validation",
                    requirement_id=item.requirement_id,
                    message=f"Duplicate requirement ID: '{item.requirement_id}'",
                    severity="error",
                )
            )
        seen_ids.add(item.requirement_id)

        item_issues = validate_requirement_item(item, posting, posting_revision)
        all_issues.extend(item_issues)

    return all_issues

