"""Finite catalog of supported C06 posting targets and operators for C02 SearchPolicy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from job_automation.contracts.enums import EmploymentType, WorkplaceType


@dataclass(frozen=True)
class TargetDefinition:
    """Specification of a supported C06 target field."""

    field_path: str
    description: str
    allowed_operators: frozenset[str]
    allowed_for_preferences: bool = True
    valid_enum_values: frozenset[str] | None = None
    is_compensation: bool = False


# Supported workplace type values from C06 WorkplaceType enum
WORKPLACE_TYPE_VALUES: frozenset[str] = frozenset(w.value for w in WorkplaceType)

# Supported employment type values from C06 EmploymentType enum
EMPLOYMENT_TYPE_VALUES: frozenset[str] = frozenset(e.value for e in EmploymentType)

# Supported targets in C06 NormalizedPosting
TARGET_CATALOG: dict[str, TargetDefinition] = {
    "title": TargetDefinition(
        field_path="title",
        description="Job advert title",
        allowed_operators=frozenset({"equals", "not_equals", "contains", "not_contains", "in", "not_in"}),
        allowed_for_preferences=True,
    ),
    "description_clean": TargetDefinition(
        field_path="description_clean",
        description="Cleaned, HTML-stripped advert description",
        allowed_operators=frozenset({"contains", "not_contains"}),
        allowed_for_preferences=True,
    ),
    "company_name_hint": TargetDefinition(
        field_path="company_name_hint",
        description="Extracted employer or company name hint",
        allowed_operators=frozenset({"equals", "not_equals", "contains", "not_contains", "in", "not_in"}),
        allowed_for_preferences=True,
    ),
    "workplace_type": TargetDefinition(
        field_path="workplace_type",
        description="Workplace arrangement: onsite, hybrid, remote, or unknown",
        allowed_operators=frozenset({"equals", "not_equals", "in", "not_in"}),
        allowed_for_preferences=True,
        valid_enum_values=WORKPLACE_TYPE_VALUES,
    ),
    "employment_type": TargetDefinition(
        field_path="employment_type",
        description="Employment arrangement: full_time, part_time, contract, internship, temporary, unknown",
        allowed_operators=frozenset({"equals", "not_equals", "in", "not_in"}),
        allowed_for_preferences=True,
        valid_enum_values=EMPLOYMENT_TYPE_VALUES,
    ),
    "advert_language": TargetDefinition(
        field_path="advert_language",
        description="Detected or declared advert language code (e.g. 'de', 'en')",
        allowed_operators=frozenset({"equals", "not_equals", "in", "not_in"}),
        allowed_for_preferences=True,
    ),
    "locations.country": TargetDefinition(
        field_path="locations.country",
        description="ISO 3166-1 alpha-2 country code of advert location (e.g. 'DE')",
        allowed_operators=frozenset({"equals", "not_equals", "in", "not_in"}),
        allowed_for_preferences=True,
    ),
    "locations.city": TargetDefinition(
        field_path="locations.city",
        description="City name of advert location",
        allowed_operators=frozenset({"equals", "not_equals", "in", "not_in"}),
        allowed_for_preferences=True,
    ),
    "locations.region": TargetDefinition(
        field_path="locations.region",
        description="Sub-national region or Bundesland (e.g. 'Berlin', 'Bayern')",
        allowed_operators=frozenset({"equals", "not_equals", "in", "not_in"}),
        allowed_for_preferences=True,
    ),
    "remote_eligibility_restrictions": TargetDefinition(
        field_path="remote_eligibility_restrictions",
        description="Geographic restrictions on remote eligibility (e.g. ['DE', 'EU'])",
        allowed_operators=frozenset({"contains", "not_contains", "in", "not_in", "equals"}),
        allowed_for_preferences=True,
    ),
    "compensation": TargetDefinition(
        field_path="compensation",
        description="Structured compensation with currency, period, and amount bounds",
        allowed_operators=frozenset({"gte", "lte", "gt", "lt", "equals"}),
        allowed_for_preferences=False,
        is_compensation=True,
    ),
    "compensation.min_amount": TargetDefinition(
        field_path="compensation.min_amount",
        description="Minimum salary threshold with explicit currency and period",
        allowed_operators=frozenset({"gte", "lte", "gt", "lt", "equals"}),
        allowed_for_preferences=False,
        is_compensation=True,
    ),
    "compensation.max_amount": TargetDefinition(
        field_path="compensation.max_amount",
        description="Maximum salary ceiling with explicit currency and period",
        allowed_operators=frozenset({"gte", "lte", "gt", "lt", "equals"}),
        allowed_for_preferences=False,
        is_compensation=True,
    ),
}

SUPPORTED_TARGET_NAMES: frozenset[str] = frozenset(TARGET_CATALOG.keys())


def is_candidate_field(field_name: str) -> bool:
    """Return True if field_name references candidate facts rather than posting fields."""
    normalized = field_name.strip().lower()
    return (
        normalized.startswith("candidate.")
        or normalized.startswith("candidate_")
        or normalized in {
            "work_authorization",
            "work_authorization_countries",
            "candidate_skills",
            "candidate_languages",
            "language_proficiencies",
        }
    )


def is_skills_target(field_name: str) -> bool:
    """Return True if field_name attempts to target raw 'skills' which is not on C06."""
    return field_name.strip().lower() == "skills"

