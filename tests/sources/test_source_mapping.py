"""Tests for source mapping conventions and vocabulary (SOURCE-02-S03)."""

from __future__ import annotations

import pytest

from job_automation.contracts.primitives import SourceKey
from job_automation.sources.adapters.mapping import (
    STANDARD_MAPPED_FIELDS,
    map_raw_record_to_draft_fields,
)


def test_standard_mapped_fields_vocabulary() -> None:
    expected = {
        "title",
        "company_name_hint",
        "description",
        "source_url",
        "application_url",
        "locations_raw",
        "workplace_type_raw",
        "employment_type_raw",
        "compensation_raw",
        "source_published_raw",
        "source_deadline_raw",
    }
    assert STANDARD_MAPPED_FIELDS == expected


def test_map_raw_record_complete() -> None:
    raw_data = {
        "source_url": "https://jobs.example.invalid/001",
        "title": "Staff Engineer",
        "company": "Enterprise AG",
        "text": "<p>We are hiring a Staff Engineer.</p>",
        "application_url": "https://jobs.example.invalid/apply/001",
        "locations_raw": ["Berlin", "Munich"],
        "compensation_raw": "90.000 EUR",
    }
    sk = SourceKey(provider="manual", board_id="b1", source_posting_id="001")
    mapped, issues = map_raw_record_to_draft_fields(
        raw_data,
        input_ref="memory://001",
        input_hash="sha256:" + "0" * 64,
        record_index=1,
        source_key=sk,
    )
    assert len(issues) == 0
    assert mapped["title"] == "Staff Engineer"
    assert mapped["company_name_hint"] == "Enterprise AG"
    assert mapped["description"] == "<p>We are hiring a Staff Engineer.</p>"
    assert mapped["source_url"] == "https://jobs.example.invalid/001"
    assert mapped["locations_raw"] == ["Berlin", "Munich"]
    assert mapped["compensation_raw"] == "90.000 EUR"
    assert mapped["mapping_version"] == "1.0"
    assert mapped["provenance"]["title"] == "title"


def test_map_raw_record_missing_title_produces_warning() -> None:
    raw_data = {
        "source_url": "https://jobs.example.invalid/002",
        "text": "Job description without title.",
    }
    mapped, issues = map_raw_record_to_draft_fields(
        raw_data,
        input_ref="memory://002",
        input_hash="sha256:" + "0" * 64,
        record_index=2,
    )
    assert mapped["title"] is None
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "missing_title"


def test_map_raw_record_missing_required_fields_produces_blocking_errors() -> None:
    raw_data = {
        "title": "Title Without URL or Text",
    }
    mapped, issues = map_raw_record_to_draft_fields(
        raw_data,
        input_ref="memory://003",
        input_hash="sha256:" + "0" * 64,
        record_index=3,
    )
    assert len(issues) == 2
    codes = {iss.code for iss in issues}
    assert "missing_source_url" in codes
    assert "missing_posting_text" in codes
    assert all(iss.severity == "error" for iss in issues)

