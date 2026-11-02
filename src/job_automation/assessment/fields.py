"""Field accessor table for C06 NormalizedPosting attributes."""

from __future__ import annotations

from typing import Any

from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.fields import TARGET_CATALOG, is_candidate_field, is_skills_target


def get_posting_field_value(
    posting: NormalizedPosting,
    field_path: str,
) -> tuple[Any, bool]:
    """Retrieve target field value from NormalizedPosting.

    Returns:
        tuple[Any, bool]: (value, is_present)
        If the field is absent or not set, is_present is False.
    """
    field_path = field_path.strip()

    if is_candidate_field(field_path) or is_skills_target(field_path):
        return None, False

    if field_path not in TARGET_CATALOG:
        return None, False

    if field_path == "title":
        return posting.title, bool(posting.title)

    if field_path == "description_clean":
        return posting.description_clean, bool(posting.description_clean)

    if field_path == "company_name_hint":
        return posting.company_name_hint, bool(posting.company_name_hint)

    if field_path == "workplace_type":
        # Returns string value of enum, e.g. "remote", "onsite", "hybrid", "unknown"
        val = posting.workplace_type.value if posting.workplace_type else "unknown"
        # If unknown, it represents unspecified/unknown arrangement
        return val, val != "unknown"

    if field_path == "employment_type":
        val = posting.employment_type.value if posting.employment_type else "unknown"
        return val, val != "unknown"

    if field_path == "advert_language":
        return posting.advert_language, posting.advert_language is not None

    if field_path == "locations.country":
        if not posting.locations:
            return [], False
        countries = [loc.country for loc in posting.locations if loc.country is not None]
        return countries, len(countries) > 0

    if field_path == "locations.city":
        if not posting.locations:
            return [], False
        cities = [loc.city for loc in posting.locations if loc.city is not None]
        return cities, len(cities) > 0

    if field_path == "locations.region":
        if not posting.locations:
            return [], False
        regions = [loc.region for loc in posting.locations if loc.region is not None]
        return regions, len(regions) > 0

    if field_path == "remote_eligibility_restrictions":
        # Stored as list of strings, e.g. ['DE', 'EU']
        return posting.remote_eligibility_restrictions, len(posting.remote_eligibility_restrictions) > 0

    if field_path == "compensation":
        return posting.compensation, posting.compensation is not None

    if field_path == "compensation.min_amount":
        if posting.compensation and posting.compensation.min_amount is not None:
            return posting.compensation.min_amount, True
        return None, False

    if field_path == "compensation.max_amount":
        if posting.compensation and posting.compensation.max_amount is not None:
            return posting.compensation.max_amount, True
        return None, False

    return None, False

