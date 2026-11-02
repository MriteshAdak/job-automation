"""Internal document consistency and entity attribution validation (GEN-04-S04)."""
from __future__ import annotations

from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.primitives import PrecisionDate
from job_automation.generation.validation_dates import date_to_interval, validate_calendar_date
from job_automation.generation.validation_records import DocumentValidationIssue


def validate_internal_consistency(
    draft: DraftDocumentV2,
    source_map: dict[str, Any],
) -> list[DocumentValidationIssue]:
    """Validate cross-claim and entry-level entity consistency."""
    issues: list[DocumentValidationIssue] = []
    resolved_claims = source_map.get("claims", {})
    facts_by_id = source_map.get("facts_by_id", {})

    # 1. Role / Education Entry Attribution Consistency
    # In CV sections (experience, education), each entry should represent ONE coherent source entity
    for section in draft.sections:
        if section.heading_key in ("experience", "education"):
            for entry in section.entries:
                entry_entities: set[Any] = set()
                for cid in entry.claim_ids:
                    rc = resolved_claims.get(cid)
                    if rc and rc.get("subject") == "candidate":
                        f = rc.get("fact")
                        if f:
                            # Root entity ID
                            p_id = getattr(f, "parent_fact_id", None)
                            root_id = p_id if p_id else f.fact_id
                            entry_entities.add(root_id)

                if len(entry_entities) > 1:
                    issues.append(
                        DocumentValidationIssue(
                            code="inconsistent_entry_attribution",
                            severity="fatal",
                            message=f"Entry '{entry.entry_id}' combines claims from {len(entry_entities)} distinct root role/education facts",
                            entry_id=entry.entry_id,
                            section_id=section.section_id,
                            suggested_action="Separate distinct employment or education entities into distinct entries",
                        )
                    )

    # 2. Cross-Occurrence Consistency for the same Fact / Entity
    # If the same fact is cited multiple times for title or dates, verify values match across occurrences
    seen_titles: dict[Any, tuple[str, str]] = {}  # fact_id -> (text, claim_id)
    seen_dates: dict[tuple[Any, str], tuple[str, str]] = {}  # (fact_id, field) -> (text, claim_id)

    for claim in draft.claims:
        cid = claim.claim_id
        rc = resolved_claims.get(cid)
        if not rc or rc.get("subject") != "candidate":
            continue

        fact = rc.get("fact")
        if not fact:
            continue

        fid = fact.fact_id

        if claim.source_field == "title":
            if fid in seen_titles:
                prev_text, prev_cid = seen_titles[fid]
                if claim.text != prev_text:
                    issues.append(
                        DocumentValidationIssue(
                            code="internal_title_conflict",
                            severity="fatal",
                            message=f"Conflicting titles for same fact '{fid}': '{claim.text}' vs '{prev_text}'",
                            claim_id=cid,
                            suggested_action="Ensure consistent titles for the same entity across the document",
                        )
                    )
            else:
                seen_titles[fid] = (claim.text, cid)

        if claim.source_field in ("start_date", "end_date"):
            key = (fid, claim.source_field)
            if key in seen_dates:
                prev_text, prev_cid = seen_dates[key]
                if claim.text != prev_text:
                    issues.append(
                        DocumentValidationIssue(
                            code="internal_date_conflict",
                            severity="fatal",
                            message=f"Conflicting {claim.source_field} for same fact '{fid}': '{claim.text}' vs '{prev_text}'",
                            claim_id=cid,
                            suggested_action="Ensure consistent dates for the same entity across the document",
                        )
                    )
            else:
                seen_dates[key] = (claim.text, cid)

    # 3. Timeline Overlap Check Across Distinct Role Facts (Warning only!)
    # Distinct roles can be concurrent; emit warning rather than fatal error
    role_date_intervals: list[tuple[Any, tuple[tuple[int, int, int], tuple[int, int, int]]]] = []
    seen_role_facts = set()

    for claim in draft.claims:
        rc = resolved_claims.get(claim.claim_id)
        if not rc or rc.get("subject") != "candidate":
            continue
        fact = rc.get("fact")
        if not fact or fact.fact_id in seen_role_facts:
            continue
        if getattr(fact, "kind", None) in ("role", "employment"):
            s_date = getattr(fact, "start_date", None)
            e_date = getattr(fact, "end_date", None)
            if isinstance(s_date, PrecisionDate) and isinstance(e_date, PrecisionDate):
                if validate_calendar_date(s_date) and validate_calendar_date(e_date):
                    s_early, _ = date_to_interval(s_date)
                    _, e_late = date_to_interval(e_date)
                    role_date_intervals.append((fact.fact_id, (s_early, e_late)))
                    seen_role_facts.add(fact.fact_id)

    # Compare pairs
    for i in range(len(role_date_intervals)):
        for j in range(i + 1, len(role_date_intervals)):
            fid1, (s1, e1) = role_date_intervals[i]
            fid2, (s2, e2) = role_date_intervals[j]
            # Overlap condition: max(s1, s2) <= min(e1, e2)
            if max(s1, s2) <= min(e1, e2):
                issues.append(
                    DocumentValidationIssue(
                        code="overlapping_role_dates",
                        severity="warning",
                        message=f"Roles '{fid1}' and '{fid2}' have overlapping date intervals; verify concurrent employment",
                        review_reason="source_uncertainty",
                        suggested_action="Review whether candidate held these roles concurrently",
                    )
                )

    return issues

