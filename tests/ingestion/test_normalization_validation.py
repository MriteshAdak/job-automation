"""Tests for composed normalization validation and field provenance (INGEST-02-S07)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.postings import NormalizedPosting
from job_automation.ingestion.normalization import (
    DefaultNormalizer,
    InMemoryRawProvenanceReader,
)
from tests.fakes.normalization_inputs import create_sample_draft


def test_field_provenance_populated_for_all_outputs() -> None:
    """Every populated field in NormalizedPosting has a traceable field_provenance entry."""
    reader = InMemoryRawProvenanceReader()
    draft = create_sample_draft(reader=reader)
    normalizer = DefaultNormalizer(raw_reader=reader)

    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    prov = posting.field_provenance
    assert "title" in prov
    assert "company_name_hint" in prov
    assert "description_clean" in prov
    assert "source_url" in prov
    assert "locations" in prov
    assert "workplace_type" in prov
    assert "employment_type" in prov
    assert "compensation" in prov
    assert "source_published_at" in prov
    assert "observed_at" in prov
    assert prov["observed_at"] == "fetch_time"


def test_warning_only_issues_allow_c06_posting() -> None:
    """Non-blocking warnings (e.g. date-only precision, missing compensation period) permit valid C06."""
    reader = InMemoryRawProvenanceReader()
    draft = create_sample_draft(
        source_deadline_raw="2026-12-31",  # date-only warning
        compensation_raw="75.000 EUR",  # missing period warning
        workplace_type_raw=False,  # ambiguous false remote warning
        reader=reader,
    )
    normalizer = DefaultNormalizer(raw_reader=reader)

    posting, issues = normalizer.normalize(draft)

    # Valid C06 posting produced
    assert posting is not None
    assert isinstance(posting, NormalizedPosting)

    # Unknown fields remain unknown
    assert posting.source_deadline_at is None
    assert posting.compensation is None
    assert posting.workplace_type == WorkplaceType.UNKNOWN

    # Warnings emitted
    assert len(issues) > 0
    assert not any(iss.severity == "error" for iss in issues)
    codes = {iss.code for iss in issues}
    assert "unsupported_representation" in codes
    assert "ambiguous_value" in codes


def test_blocking_error_prevents_c06_posting() -> None:
    """Fatal error on any field strictly prevents C06 posting creation."""
    reader = InMemoryRawProvenanceReader()
    # Script-only description is empty after cleaning
    draft = create_sample_draft(
        description="<script>alert('bad');</script>",
        reader=reader,
    )
    normalizer = DefaultNormalizer(raw_reader=reader)

    posting, issues = normalizer.normalize(draft)

    assert posting is None
    assert any(iss.severity == "error" for iss in issues)
    assert any(iss.code == "empty_after_cleaning" for iss in issues)

