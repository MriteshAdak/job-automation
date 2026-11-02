"""Deterministic revision content hashing for C06 NormalizedPosting.

Freezes an explicit field-by-field projection excluding observation timestamps,
raw hashes/references, and normalizer versions so that material content changes
reliably create new revisions while metadata-only sightings reuse revisions.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from job_automation.contracts.postings import NormalizedPosting


def compute_revision_content_projection(normalized: NormalizedPosting) -> dict[str, Any]:
    """Extract deterministic content dictionary for revision hashing."""
    # Deterministically sort locations
    sorted_locations = [
        {
            "country": loc.country,
            "region": loc.region,
            "city": loc.city,
            "postal_code": loc.postal_code,
            "raw_text": loc.raw_text.strip(),
        }
        for loc in sorted(
            normalized.locations,
            key=lambda l: (
                l.country or "",
                l.region or "",
                l.city or "",
                l.postal_code or "",
                l.raw_text.strip(),
            ),
        )
    ]

    # Deterministically serialize compensation
    comp_dict: dict[str, Any] | None = None
    if normalized.compensation is not None:
        c = normalized.compensation
        comp_dict = {
            "min_amount": str(c.min_amount) if c.min_amount is not None else None,
            "max_amount": str(c.max_amount) if c.max_amount is not None else None,
            "currency": c.currency,
            "period": c.period.value,
            "is_gross": c.is_gross,
            "provenance": c.provenance.value,
        }

    return {
        "title": normalized.title.strip(),
        "description_clean": normalized.description_clean.strip(),
        "company_name_hint": normalized.company_name_hint.strip(),
        "locations": sorted_locations,
        "workplace_type": normalized.workplace_type.value,
        "remote_eligibility_restrictions": sorted(normalized.remote_eligibility_restrictions),
        "employment_type": normalized.employment_type.value,
        "compensation": comp_dict,
        "advert_language": normalized.advert_language,
        "source_url": normalized.source_url.strip(),
        "application_url": (
            normalized.application_url.strip() if normalized.application_url else None
        ),
    }


def compute_revision_content_hash(normalized: NormalizedPosting) -> str:
    """Produce versioned SHA-256 digest of normalized content projection."""
    projection = compute_revision_content_projection(normalized)
    serialized = json.dumps(projection, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"

