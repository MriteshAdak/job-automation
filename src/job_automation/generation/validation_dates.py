"""Date precision, calendar validity, and chronological consistency (GEN-04-S03)."""
from __future__ import annotations

import calendar
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.primitives import PrecisionDate
from job_automation.generation.validation_records import DocumentValidationIssue


def _is_leap_year(year: int) -> bool:
    return calendar.isleap(year)


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _parse_precision_date(date: PrecisionDate) -> tuple[int, int | None, int | None]:
    parts = [int(p) for p in date.value.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else None
    day = parts[2] if len(parts) > 2 else None
    return year, month, day


def validate_calendar_date(date: PrecisionDate) -> bool:
    """Validate calendar date correctness, including leap years."""
    year, month, day = _parse_precision_date(date)
    if year < 1900 or year > 2100:
        return False
    if month is not None:
        if month < 1 or month > 12:
            return False
        if day is not None:
            max_days = _days_in_month(year, month)
            if day < 1 or day > max_days:
                return False
    elif day is not None:
        return False
    return True


def date_to_interval(date: PrecisionDate) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return (earliest_possible, latest_possible) as (year, month, day) tuples."""
    year, month, day = _parse_precision_date(date)
    if date.precision == "year":
        return ((year, 1, 1), (year, 12, 31))
    elif date.precision == "month":
        assert month is not None
        max_d = _days_in_month(year, month)
        return ((year, month, 1), (year, month, max_d))
    else:
        assert month is not None and day is not None
        pt = (year, month, day)
        return (pt, pt)


def validate_dates(
    draft: DraftDocumentV2,
    source_map: dict[str, Any],
) -> list[DocumentValidationIssue]:
    """Validate all date claims and chronological ordering."""
    issues: list[DocumentValidationIssue] = []
    facts_by_id = source_map.get("facts_by_id", {})
    resolved_claims = source_map.get("claims", {})

    checked_facts_for_range: set[Any] = set()

    for claim in draft.claims:
        if claim.source_field in ("start_date", "end_date") and claim.claim_subject == "candidate":
            cid = claim.claim_id
            resolved = resolved_claims.get(cid)
            if not resolved or "fact" not in resolved:
                continue

            fact = resolved["fact"]
            orig_val = getattr(fact, claim.source_field, None)

            # Null date handling
            if orig_val is None:
                # Under published C01, null end date means unspecified/unknown.
                # It cannot be converted to a specific date or "Present" / "heute"
                lower_text = claim.text.strip().lower()
                forbidden_ongoing_terms = {"present", "heute", "current", "ongoing", "jetzt", "bis heute"}
                if lower_text in forbidden_ongoing_terms or any(c.isdigit() for c in lower_text):
                    issues.append(
                        DocumentValidationIssue(
                            code="null_date_converted",
                            severity="fatal",
                            message=f"Null {claim.source_field} converted to asserted value '{claim.text}' without supporting approved evidence",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=claim.evidence_reference,
                            suggested_action="Null dates must remain omitted or unasserted under current recipe",
                        )
                    )
            elif isinstance(orig_val, PrecisionDate):
                # Calendar validity
                if not validate_calendar_date(orig_val):
                    issues.append(
                        DocumentValidationIssue(
                            code="invalid_calendar_date",
                            severity="fatal",
                            message=f"Source date '{orig_val.value}' fails calendar validity rules",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=claim.evidence_reference,
                        )
                    )

                # Under extractive recipe, claim text must equal exact precision date value
                if claim.text != orig_val.value:
                    issues.append(
                        DocumentValidationIssue(
                            code="date_text_altered",
                            severity="fatal",
                            message=f"Date claim text '{claim.text}' does not match frozen source date value '{orig_val.value}'",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=claim.evidence_reference,
                            suggested_action="Preserve exact source date formatting (e.g. YYYY or YYYY-MM)",
                        )
                    )

            # Check start_date <= end_date for this fact once
            if fact.fact_id not in checked_facts_for_range:
                checked_facts_for_range.add(fact.fact_id)
                s_date = getattr(fact, "start_date", None)
                e_date = getattr(fact, "end_date", None)
                if isinstance(s_date, PrecisionDate) and isinstance(e_date, PrecisionDate):
                    if validate_calendar_date(s_date) and validate_calendar_date(e_date):
                        s_early, s_late = date_to_interval(s_date)
                        e_early, e_late = date_to_interval(e_date)
                        if s_early > e_late:
                            issues.append(
                                DocumentValidationIssue(
                                    code="reversed_date_range",
                                    severity="fatal",
                                    message=f"Start date interval ({s_early}..{s_late}) is strictly after end date interval ({e_early}..{e_late})",
                                    claim_id=cid,
                                    source_field=claim.source_field,
                                    evidence_reference=claim.evidence_reference,
                                )
                            )
                        elif s_late > e_early and s_early <= e_late and (s_date.precision != "day" or e_date.precision != "day"):
                            issues.append(
                                DocumentValidationIssue(
                                    code="uncertain_date_order",
                                    severity="warning",
                                    message=f"Partial date precision ({s_date.value} to {e_date.value}) has overlapping uncertainty interval",
                                    claim_id=cid,
                                    source_field=claim.source_field,
                                    evidence_reference=claim.evidence_reference,
                                    review_reason="source_uncertainty",
                                    suggested_action="Review timeline to verify chronological progression",
                                )
                            )

    return issues

