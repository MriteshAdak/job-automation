"""Tests for location normalization and structured location preservation (INGEST-02-S05)."""

from __future__ import annotations

import pytest

from job_automation.contracts.postings import StructuredLocation
from job_automation.ingestion.normalization.locations import normalize_locations


def test_normalize_single_string_location() -> None:
    """Single location string normalizes country alias and preserves original text."""
    locs, issues = normalize_locations("Berlin, Germany")
    assert len(locs) == 1
    assert locs[0].raw_text == "Berlin, Germany"
    assert locs[0].city == "Berlin"
    assert locs[0].country == "DE"
    assert not issues


def test_normalize_list_of_string_locations() -> None:
    """Multiple location strings preserve stable order and normalize aliases."""
    input_locs = ["Berlin, Germany", "Hamburg, Deutschland"]
    locs, issues = normalize_locations(input_locs)

    assert len(locs) == 2
    assert locs[0].city == "Berlin"
    assert locs[0].country == "DE"
    assert locs[1].city == "Hamburg"
    assert locs[1].country == "DE"
    assert not issues


def test_normalize_semicolon_separated_locations() -> None:
    """Semicolon-separated string produces multiple structured locations."""
    locs, issues = normalize_locations("Köln, Deutschland; München, Deutschland")
    assert len(locs) == 2
    assert locs[0].city == "Köln"
    assert locs[0].country == "DE"
    assert locs[1].city == "München"
    assert locs[1].country == "DE"


def test_ambiguous_location_has_no_invented_country() -> None:
    """Ambiguous locations like Springfield have no guessed country."""
    locs, issues = normalize_locations("Springfield")
    assert len(locs) == 1
    assert locs[0].city == "Springfield"
    assert locs[0].country is None
    assert not issues


def test_region_preservation() -> None:
    """German Bundesland is extracted into region field."""
    locs, issues = normalize_locations("Baden-Württemberg, Deutschland")
    assert len(locs) == 1
    assert locs[0].region == "Baden-Württemberg"
    assert locs[0].country == "DE"


def test_structured_dict_location_normalization() -> None:
    """Structured location dictionaries normalize correctly."""
    input_dict = [
        {"city": "Frankfurt", "country": "Deutschland", "postal_code": "60311"}
    ]
    locs, issues = normalize_locations(input_dict)
    assert len(locs) == 1
    assert locs[0].city == "Frankfurt"
    assert locs[0].country == "DE"
    assert locs[0].postal_code == "60311"


def test_exact_duplicate_deduplication() -> None:
    """Exact repeated locations are deduplicated while preserving order."""
    input_locs = ["Berlin, Germany", "Hamburg, Germany", "Berlin, Germany"]
    locs, issues = normalize_locations(input_locs)
    assert len(locs) == 2
    assert locs[0].city == "Berlin"
    assert locs[1].city == "Hamburg"


def test_invalid_location_type_rejected() -> None:
    """Invalid item types in locations produce invalid_field_type errors."""
    locs_bool, issues_bool = normalize_locations(True)
    assert locs_bool == []
    assert any(iss.code == "invalid_field_type" for iss in issues_bool)

    locs_bad_item, issues_bad_item = normalize_locations(["Berlin", 12345])
    assert locs_bad_item == []
    assert any(iss.code == "invalid_field_type" for iss in issues_bad_item)

