"""Location normalization and structured location preservation (INGEST-02).

Preserves multiple locations in stable order while normalizing country/region/city facts:
- Preserves original raw_text for every location.
- Normalizes supported country aliases (Deutschland/Germany → DE, Österreich → AT, etc.).
- Never guesses country from source market (Springfield has no invented country).
- Never broad-comma-splits city/region/country into separate location items.
- Preserves stable source order and removes only exact duplicate entries.
"""

from __future__ import annotations

import re
from typing import Any

from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.postings import StructuredLocation

COUNTRY_ALIASES: dict[str, str] = {
    "deutschland": "DE",
    "germany": "DE",
    "de": "DE",
    "deu": "DE",
    "österreich": "AT",
    "oesterreich": "AT",
    "austria": "AT",
    "at": "AT",
    "aut": "AT",
    "schweiz": "CH",
    "switzerland": "CH",
    "ch": "CH",
    "che": "CH",
    "united kingdom": "GB",
    "uk": "GB",
    "gb": "GB",
    "great britain": "GB",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "netherlands": "NL",
    "niederlande": "NL",
    "nl": "NL",
    "france": "FR",
    "frankreich": "FR",
    "fr": "FR",
    "poland": "PL",
    "polen": "PL",
    "pl": "PL",
}

CITY_STATES = frozenset({"berlin", "hamburg", "bremen"})

# Known German territorial regions / Bundesländer (excluding city states)
GERMAN_TERRITORIAL_REGIONS = frozenset(
    {
        "baden-württemberg",
        "bayern",
        "brandenburg",
        "hessen",
        "mecklenburg-vorpommern",
        "niedersachsen",
        "nordrhein-westfalen",
        "nrw",
        "rheinland-pfalz",
        "saarland",
        "sachsen",
        "sachsen-anhalt",
        "schleswig-holstein",
        "thüringen",
    }
)


def _parse_single_location_string(raw_str: str) -> StructuredLocation:
    """Parse a single unparsed location string into a StructuredLocation."""
    raw_text = raw_str.strip()
    country: str | None = None
    region: str | None = None
    city: str | None = None
    postal_code: str | None = None

    # Check for postal code pattern (e.g. 5 digits in Germany)
    plz_match = re.search(r"\b(\d{5})\b", raw_text)
    if plz_match:
        postal_code = plz_match.group(1)

    # Check for country alias
    # Look for country as trailing comma-separated segment or in parentheses
    parts = [p.strip() for p in raw_text.split(",") if p.strip()]
    if len(parts) >= 2:
        last_part = parts[-1].lower()
        if last_part in COUNTRY_ALIASES:
            country = COUNTRY_ALIASES[last_part]
            first_part = parts[0]
            # First part is likely city or city / remote
            city_candidate = first_part.split("/")[0].strip()
            cand_lower = city_candidate.lower()
            if cand_lower in CITY_STATES:
                city = city_candidate
                region = city_candidate
            elif cand_lower in GERMAN_TERRITORIAL_REGIONS:
                region = city_candidate
            else:
                city = city_candidate
        else:
            # First part city, second part maybe region or country
            city_candidate = parts[0].split("/")[0].strip()
            city = city_candidate
    else:
        # Single segment: e.g. "Berlin", "Hamburg, Deutschland" (handled above), "Berlin / Remote"
        segment = raw_text.split("/")[0].strip()
        # Check if country inside parentheses: e.g. "Remote (Deutschland)"
        paren_match = re.search(r"\(([^)]+)\)", raw_text)
        if paren_match:
            paren_content = paren_match.group(1).strip().lower()
            if paren_content in COUNTRY_ALIASES:
                country = COUNTRY_ALIASES[paren_content]

        # Check if segment matches country or city or region
        seg_lower = segment.lower()
        if seg_lower in COUNTRY_ALIASES:
            country = COUNTRY_ALIASES[seg_lower]
        elif seg_lower in CITY_STATES:
            city = segment
            region = segment
        elif seg_lower in GERMAN_TERRITORIAL_REGIONS:
            region = segment
        else:
            city = segment

    return StructuredLocation(
        raw_text=raw_text,
        country=country,
        region=region,
        city=city,
        postal_code=postal_code,
    )


def normalize_locations(
    locations_raw: Any,
) -> tuple[list[StructuredLocation], list[ValidationIssue]]:
    """Normalize raw locations into a list of StructuredLocation models.

    Preserves stable ordering and original text, removing only exact duplicate entries.
    Returns:
        (locations, issues)
    """
    if locations_raw is None:
        return [], []

    # Explicitly reject boolean
    if isinstance(locations_raw, bool):
        return [], [
            ValidationIssue(
                field_path="locations",
                code="invalid_field_type",
                message="locations must not be a boolean",
                severity="error",
            )
        ]

    # Single string
    if isinstance(locations_raw, str):
        trimmed = locations_raw.strip()
        if not trimmed:
            return [], []

        # If string contains semicolon separator, split into multiple location items
        if ";" in trimmed:
            items = [seg.strip() for seg in trimmed.split(";") if seg.strip()]
        else:
            items = [trimmed]

        res: list[StructuredLocation] = []
        for it in items:
            loc = _parse_single_location_string(it)
            res.append(loc)
        return res, []

    # List of items
    if isinstance(locations_raw, list):
        parsed_locations: list[StructuredLocation] = []
        seen_keys: set[tuple[str, str | None, str | None, str | None, str | None]] = set()

        for idx, item in enumerate(locations_raw):
            if isinstance(item, bool) or not isinstance(item, (str, dict)):
                return [], [
                    ValidationIssue(
                        field_path=f"locations[{idx}]",
                        code="invalid_field_type",
                        message=(
                            f"Location item at index {idx} must be a string or object, "
                            f"got {type(item).__name__}"
                        ),
                        severity="error",
                    )
                ]

            if isinstance(item, str):
                trimmed = item.strip()
                if not trimmed:
                    continue
                loc = _parse_single_location_string(trimmed)
            else:
                # Structured dictionary
                raw_text = str(
                    item.get("raw_text") or item.get("text") or item.get("city") or ""
                ).strip()
                if not raw_text:
                    city_part = item.get("city")
                    country_part = item.get("country")
                    raw_text = ", ".join(p for p in (city_part, country_part) if p) or "Unknown"

                c_val = item.get("country")
                country = None
                if c_val and isinstance(c_val, str):
                    country = COUNTRY_ALIASES.get(c_val.strip().lower(), c_val.strip().upper())

                loc = StructuredLocation(
                    raw_text=raw_text,
                    country=country,
                    region=item.get("region"),
                    city=item.get("city"),
                    postal_code=item.get("postal_code"),
                )

            dedup_key = (loc.raw_text, loc.country, loc.region, loc.city, loc.postal_code)
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                parsed_locations.append(loc)

        return parsed_locations, []

    # Other invalid container type
    return [], [
        ValidationIssue(
            field_path="locations",
            code="invalid_field_type",
            message=f"locations must be a string or array, got {type(locations_raw).__name__}",
            severity="error",
        )
    ]
