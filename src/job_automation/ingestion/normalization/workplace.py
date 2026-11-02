"""Workplace type, remote restrictions, and employment type normalization (INGEST-02).

Normalizes workplace arrangements and employment types:
- Maps explicit workplace aliases (vor Ort/on-site, hybrid, remote).
- Treats boolean remote=False as unknown (does not imply onsite over hybrid).
- Enforces that remote does NOT imply worldwide eligibility; missing restrictions
  remain unknown/empty without fabricating worldwide eligibility.
- Preserves explicit regional restrictions (DE, EU).
- Collapses equivalent employment labels (Vollzeit, Full-time) and treats incompatible
  simultaneous labels as unknown with warnings.
"""

from __future__ import annotations

import re
from typing import Any

from job_automation.contracts.enums import EmploymentType, WorkplaceType
from job_automation.contracts.errors import ValidationIssue
from job_automation.ingestion.normalization.locations import COUNTRY_ALIASES

# Workplace alias mappings
REMOTE_KEYWORDS = frozenset(
    {
        "remote",
        "homeoffice",
        "home-office",
        "vollständig remote",
        "telework",
        "work from home",
        "100% remote",
    }
)

HYBRID_KEYWORDS = frozenset(
    {
        "hybrid",
        "teilweise remote",
        "hybrid (remote/onsite)",
        "remote/onsite",
    }
)

ONSITE_KEYWORDS = frozenset(
    {
        "onsite",
        "on-site",
        "vor ort",
        "in-office",
        "präsenz",
        "office",
    }
)

# Employment alias mappings
EMPLOYMENT_ALIASES: dict[str, EmploymentType] = {
    "full_time": EmploymentType.FULL_TIME,
    "full-time": EmploymentType.FULL_TIME,
    "full time": EmploymentType.FULL_TIME,
    "vollzeit": EmploymentType.FULL_TIME,
    "permanent": EmploymentType.FULL_TIME,
    "festanstellung": EmploymentType.FULL_TIME,
    "part_time": EmploymentType.PART_TIME,
    "part-time": EmploymentType.PART_TIME,
    "part time": EmploymentType.PART_TIME,
    "teilzeit": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT,
    "contractor": EmploymentType.CONTRACT,
    "freelance": EmploymentType.CONTRACT,
    "freelancer": EmploymentType.CONTRACT,
    "freie mitarbeit": EmploymentType.CONTRACT,
    "internship": EmploymentType.INTERNSHIP,
    "intern": EmploymentType.INTERNSHIP,
    "praktikum": EmploymentType.INTERNSHIP,
    "praktikant": EmploymentType.INTERNSHIP,
    "werkstudent": EmploymentType.INTERNSHIP,
    "working student": EmploymentType.INTERNSHIP,
    "temporary": EmploymentType.TEMPORARY,
    "temp": EmploymentType.TEMPORARY,
    "befristet": EmploymentType.TEMPORARY,
}


def normalize_workplace(
    workplace_raw: Any,
    restrictions_raw: Any = None,
) -> tuple[WorkplaceType, list[str], list[ValidationIssue]]:
    """Normalize workplace arrangement and remote eligibility restrictions.

    Returns:
        (workplace_type, remote_restrictions, issues)
    """
    issues: list[ValidationIssue] = []
    workplace_type = WorkplaceType.UNKNOWN
    remote_restrictions: list[str] = []

    # 1. Normalize workplace type
    if workplace_raw is not None:
        if isinstance(workplace_raw, bool):
            if workplace_raw:
                workplace_type = WorkplaceType.REMOTE
            else:
                # Boolean false does not establish onsite rather than hybrid
                workplace_type = WorkplaceType.UNKNOWN
                issues.append(
                    ValidationIssue(
                        field_path="workplace_type",
                        code="ambiguous_value",
                        message=(
                            "Boolean remote=False does not distinguish onsite from hybrid; "
                            "workplace_type remains unknown"
                        ),
                        severity="warning",
                    )
                )
        elif isinstance(workplace_raw, str):
            raw_str = workplace_raw.strip().lower()
            if raw_str:
                has_remote = any(kw in raw_str for kw in REMOTE_KEYWORDS)
                has_hybrid = any(kw in raw_str for kw in HYBRID_KEYWORDS)
                has_onsite = any(kw in raw_str for kw in ONSITE_KEYWORDS)

                if has_hybrid or (has_remote and has_onsite and "hybrid" in raw_str):
                    workplace_type = WorkplaceType.HYBRID
                elif has_remote and has_onsite:
                    # Conflicting assertions without hybrid label
                    workplace_type = WorkplaceType.UNKNOWN
                    issues.append(
                        ValidationIssue(
                            field_path="workplace_type",
                            code="conflicting_values",
                            message=(
                                f"Workplace text '{workplace_raw}' asserts both onsite and remote "
                                "without hybrid resolution; remains unknown"
                            ),
                            severity="warning",
                        )
                    )
                elif has_remote:
                    workplace_type = WorkplaceType.REMOTE
                elif has_onsite:
                    workplace_type = WorkplaceType.ONSITE
                else:
                    workplace_type = WorkplaceType.UNKNOWN
                    issues.append(
                        ValidationIssue(
                            field_path="workplace_type",
                            code="unsupported_representation",
                            message=f"Unsupported workplace text '{workplace_raw}'; mapped as unknown",
                            severity="warning",
                        )
                    )

                # Check for inline restriction: e.g. "Remote (Deutschland)", "Remote (EU)"
                paren_match = re.search(r"\(([^)]+)\)", raw_str)
                if paren_match and restrictions_raw is None:
                    inner = paren_match.group(1).strip()
                    # Check if region/country
                    inner_norm = COUNTRY_ALIASES.get(inner, inner.upper())
                    if inner_norm in ("DE", "AT", "CH", "EU", "GB", "US"):
                        remote_restrictions.append(inner_norm)
        else:
            issues.append(
                ValidationIssue(
                    field_path="workplace_type",
                    code="invalid_field_type",
                    message=f"workplace_type_raw must be a string or boolean, got {type(workplace_raw).__name__}",
                    severity="error",
                )
            )

    # 2. Normalize remote restrictions if explicitly provided
    if restrictions_raw is not None:
        if isinstance(restrictions_raw, bool):
            issues.append(
                ValidationIssue(
                    field_path="remote_eligibility_restrictions",
                    code="invalid_field_type",
                    message="remote_eligibility_restrictions must not be a boolean",
                    severity="error",
                )
            )
        elif isinstance(restrictions_raw, str):
            r_str = restrictions_raw.strip().lower()
            if r_str in ("worldwide", "global", "anywhere", "unrestricted"):
                # Explicitly worldwide: empty restrictions list
                remote_restrictions = []
            elif r_str in COUNTRY_ALIASES:
                remote_restrictions = [COUNTRY_ALIASES[r_str]]
            elif r_str.upper() in ("DE", "AT", "CH", "EU", "GB", "US"):
                remote_restrictions = [r_str.upper()]
            elif r_str:
                remote_restrictions = [restrictions_raw.strip()]
        elif isinstance(restrictions_raw, list):
            res_list: list[str] = []
            for idx, r_item in enumerate(restrictions_raw):
                if not isinstance(r_item, str):
                    issues.append(
                        ValidationIssue(
                            field_path=f"remote_eligibility_restrictions[{idx}]",
                            code="invalid_field_type",
                            message=f"Restriction member must be string, got {type(r_item).__name__}",
                            severity="error",
                        )
                    )
                    continue
                item_lower = r_item.strip().lower()
                if item_lower in ("worldwide", "global", "anywhere", "unrestricted"):
                    continue
                if item_lower in COUNTRY_ALIASES:
                    res_list.append(COUNTRY_ALIASES[item_lower])
                else:
                    res_list.append(r_item.strip().upper())
            remote_restrictions = res_list
        else:
            issues.append(
                ValidationIssue(
                    field_path="remote_eligibility_restrictions",
                    code="invalid_field_type",
                    message=f"remote_eligibility_restrictions must be a list or string, got {type(restrictions_raw).__name__}",
                    severity="error",
                )
            )

    return workplace_type, remote_restrictions, issues


def normalize_employment_type(
    employment_raw: Any,
) -> tuple[EmploymentType, list[ValidationIssue]]:
    """Normalize employment type arrangement.

    Returns:
        (employment_type, issues)
    """
    if employment_raw is None:
        return EmploymentType.UNKNOWN, []

    if isinstance(employment_raw, bool):
        return EmploymentType.UNKNOWN, [
            ValidationIssue(
                field_path="employment_type",
                code="invalid_field_type",
                message="employment_type must not be a boolean",
                severity="error",
            )
        ]

    labels: list[str] = []
    if isinstance(employment_raw, str):
        trimmed = employment_raw.strip()
        if not trimmed:
            return EmploymentType.UNKNOWN, []
        labels = [trimmed]
    elif isinstance(employment_raw, list):
        for idx, item in enumerate(employment_raw):
            if not isinstance(item, str):
                return EmploymentType.UNKNOWN, [
                    ValidationIssue(
                        field_path=f"employment_type[{idx}]",
                        code="invalid_field_type",
                        message=f"Employment type member must be string, got {type(item).__name__}",
                        severity="error",
                    )
                ]
            if item.strip():
                labels.append(item.strip())
    else:
        return EmploymentType.UNKNOWN, [
            ValidationIssue(
                field_path="employment_type",
                code="invalid_field_type",
                message=f"employment_type must be a string or list of strings, got {type(employment_raw).__name__}",
                severity="error",
            )
        ]

    if not labels:
        return EmploymentType.UNKNOWN, []

    resolved: set[EmploymentType] = set()
    for lab in labels:
        norm = EMPLOYMENT_ALIASES.get(lab.lower())
        if norm is not None and norm != EmploymentType.UNKNOWN:
            resolved.add(norm)

    if not resolved:
        # None of the labels matched a known employment type
        return EmploymentType.UNKNOWN, [
            ValidationIssue(
                field_path="employment_type",
                code="unsupported_representation",
                message=f"Unsupported employment type label '{labels[0]}'; mapped as unknown",
                severity="warning",
            )
        ]

    if len(resolved) == 1:
        return next(iter(resolved)), []

    # Incompatible multiple types: e.g. Full-time and Part-time
    return EmploymentType.UNKNOWN, [
        ValidationIssue(
            field_path="employment_type",
            code="conflicting_values",
            message=(
                f"Conflicting employment types {sorted(e.value for e in resolved)} asserted simultaneously; "
                "mapped as unknown"
            ),
            severity="warning",
        )
    ]

