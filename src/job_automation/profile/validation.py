"""Invariant validation for candidate facts, parent hierarchies, dates, and permissions.

Guarantees data integrity before persistence or publication without leaking
sensitive claim text in exception messages.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Sequence

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateFact,
    ProfileSnapshot,
)
from job_automation.profile.errors import ProfileValidationError
from job_automation.profile.models import (
    SUPPORTED_PURPOSES,
    DraftFact,
    DraftProfile,
)


def _validate_calendar_date(p_date: PrecisionDate, field_name: str) -> None:
    """Validate that PrecisionDate represents an actual valid calendar date."""
    if p_date.precision == "day":
        try:
            date.fromisoformat(p_date.value)
        except ValueError as err:
            raise ProfileValidationError(
                f"Invalid calendar date for {field_name}: '{p_date.value}' is not a valid date",
                field_path=field_name,
                code="INVALID_CALENDAR_DATE",
            ) from err
    elif p_date.precision == "month":
        parts = p_date.value.split("-")
        month = int(parts[1])
        if month < 1 or month > 12:
            raise ProfileValidationError(
                f"Invalid month for {field_name}: '{p_date.value}'",
                field_path=field_name,
                code="INVALID_MONTH",
            )
    elif p_date.precision == "year":
        year = int(p_date.value)
        if year < 1900 or year > 2100:
            raise ProfileValidationError(
                f"Year out of reasonable range for {field_name}: '{p_date.value}'",
                field_path=field_name,
                code="INVALID_YEAR",
            )


def compare_precision_dates(d1: PrecisionDate, d2: PrecisionDate) -> int:
    """Compare two PrecisionDates.

    Returns:
      -1 if d1 strictly precedes d2
       0 if they overlap / are equivalent at their granularity
       1 if d1 strictly follows d2
    """
    # Normalize to comparable prefixes
    # If d1 is year (YYYY) and d2 is month (YYYY-MM):
    y1 = int(d1.value.split("-")[0])
    y2 = int(d2.value.split("-")[0])
    if y1 < y2:
        return -1
    if y1 > y2:
        return 1

    # Same year: check month if available for both
    m1 = int(d1.value.split("-")[1]) if d1.precision in ("month", "day") else None
    m2 = int(d2.value.split("-")[1]) if d2.precision in ("month", "day") else None

    if m1 is not None and m2 is not None:
        if m1 < m2:
            return -1
        if m1 > m2:
            return 1
        # Same month: check day if available for both
        day1 = int(d1.value.split("-")[2]) if d1.precision == "day" else None
        day2 = int(d2.value.split("-")[2]) if d2.precision == "day" else None
        if day1 is not None and day2 is not None:
            if day1 < day2:
                return -1
            if day1 > day2:
                return 1
            return 0
        return 0

    return 0


def _validate_date_range(start: PrecisionDate | None, end: PrecisionDate | None, fact_id: uuid.UUID) -> None:
    """Validate that start date is less than or equal to end date."""
    if start is not None:
        _validate_calendar_date(start, f"facts[{fact_id}].start_date")
    if end is not None:
        _validate_calendar_date(end, f"facts[{fact_id}].end_date")

    if start is not None and end is not None:
        cmp = compare_precision_dates(start, end)
        if cmp > 0:
            raise ProfileValidationError(
                f"Date range invalid for fact '{fact_id}': start_date ({start.value}) is after end_date ({end.value})",
                field_path=f"facts[{fact_id}].date_range",
                code="INVALID_DATE_RANGE",
            )


def _validate_fact_allowed_uses(allowed_uses: Sequence[str], fact_id: uuid.UUID) -> None:
    """Ensure allowed uses are only valid supported purposes."""
    for purpose in allowed_uses:
        if purpose not in SUPPORTED_PURPOSES:
            raise ProfileValidationError(
                f"Unsupported allowed_use '{purpose}' in fact '{fact_id}'. Must be one of {sorted(SUPPORTED_PURPOSES)}",
                field_path=f"facts[{fact_id}].allowed_uses",
                code="UNSUPPORTED_ALLOWED_USE",
            )


def validate_facts_graph(facts: Sequence[DraftFact | CandidateFact]) -> None:
    """Validate graph integrity: no duplicate IDs, valid parent references, and no cycles."""
    fact_map: dict[uuid.UUID, DraftFact | CandidateFact] = {}

    for f in facts:
        if f.fact_id in fact_map:
            raise ProfileValidationError(
                f"Duplicate fact_id found: '{f.fact_id}'",
                field_path=f"facts[{f.fact_id}]",
                code="DUPLICATE_FACT_ID",
            )
        fact_map[f.fact_id] = f

        # Validate date ranges
        _validate_date_range(f.start_date, f.end_date, f.fact_id)

        # Validate allowed uses
        _validate_fact_allowed_uses(f.allowed_uses, f.fact_id)

    # Validate parent relationships and cycle detection
    for f in facts:
        if f.parent_id is not None:
            if f.parent_id == f.fact_id:
                raise ProfileValidationError(
                    f"Self-referential parent_id in fact '{f.fact_id}'",
                    field_path=f"facts[{f.fact_id}].parent_id",
                    code="SELF_REFERENTIAL_PARENT",
                )
            if f.parent_id not in fact_map:
                raise ProfileValidationError(
                    f"Parent fact '{f.parent_id}' referenced by fact '{f.fact_id}' does not exist in profile",
                    field_path=f"facts[{f.fact_id}].parent_id",
                    code="MISSING_PARENT_FACT",
                )

    # Cycle detection via DFS
    visited: set[uuid.UUID] = set()
    visiting: set[uuid.UUID] = set()

    def check_cycle(fid: uuid.UUID) -> None:
        visiting.add(fid)
        parent_id = fact_map[fid].parent_id
        if parent_id is not None:
            if parent_id in visiting:
                raise ProfileValidationError(
                    f"Cyclic parent relationship detected involving fact '{fid}' and parent '{parent_id}'",
                    field_path=f"facts[{fid}].parent_id",
                    code="CYCLIC_PARENT_RELATIONSHIP",
                )
            if parent_id not in visited and parent_id in fact_map:
                check_cycle(parent_id)
        visiting.remove(fid)
        visited.add(fid)

    for fid in fact_map:
        if fid not in visited:
            check_cycle(fid)


def validate_draft(draft: DraftProfile) -> None:
    """Validate all invariants for an unapproved draft profile."""
    if draft.schema_version != "1.0":
        raise ProfileValidationError(
            f"Unsupported schema version: '{draft.schema_version}'",
            field_path="schema_version",
            code="UNSUPPORTED_SCHEMA_VERSION",
        )
    validate_facts_graph(draft.facts)


def validate_snapshot(snapshot: ProfileSnapshot) -> None:
    """Validate all invariants for an approved C01 snapshot."""
    if snapshot.schema_version != "1.0":
        raise ProfileValidationError(
            f"Unsupported schema version: '{snapshot.schema_version}'",
            field_path="schema_version",
            code="UNSUPPORTED_SCHEMA_VERSION",
        )
    if not snapshot.approval_metadata.is_approved:
        raise ProfileValidationError(
            "Snapshot approval_metadata must have is_approved=True",
            field_path="approval_metadata.is_approved",
            code="UNAPPROVED_SNAPSHOT",
        )
    validate_facts_graph(snapshot.evidence_records)

