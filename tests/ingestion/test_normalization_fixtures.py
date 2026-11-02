"""Tests verifying synthetic fixtures and multi-shape corpus coverage (INGEST-02-S02)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.contracts.postings import SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.normalization import (
    DefaultNormalizer,
    InMemoryRawProvenanceReader,
)
from tests.fakes.normalization_inputs import FIXED_FETCH_TIME

FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "ingestion" / "normalization"
)


def test_office_html_fixture_normalizes_cleanly() -> None:
    """office_html fixture normalizes into expected clean C06 fields."""
    fixture_path = FIXTURES_DIR / "manual_text" / "office_html.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reader = InMemoryRawProvenanceReader()
    raw_ref = "memory://fixture_office_html"
    raw_bytes = data["raw_payload"].encode("utf-8")
    reader.register(raw_ref, raw_bytes)

    draft = SourceJobDraft(
        raw_reference=raw_ref,
        source_key=SourceKey(provider="manual", board_id="text", source_posting_id="fx-01"),
        fetch_time=FIXED_FETCH_TIME,
        original_fields=data,
        source_mapped_fields=data["mapped_fields"],
    )

    normalizer = DefaultNormalizer(raw_reader=reader)
    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    assert posting.title == data["expected"]["title"]
    assert posting.company_name_hint == data["expected"]["company_name_hint"]
    assert posting.description_clean == data["expected"]["description_clean"]
    assert posting.workplace_type == data["expected"]["workplace_type"]
    assert posting.employment_type == data["expected"]["employment_type"]


def test_hostile_fixture_removes_scripts() -> None:
    """hostile_and_malformed fixture removes script tags and keeps inert plain text."""
    fixture_path = FIXTURES_DIR / "text" / "hostile_and_malformed.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reader = InMemoryRawProvenanceReader()
    raw_ref = "memory://fixture_hostile"
    raw_bytes = data["raw_payload"].encode("utf-8")
    reader.register(raw_ref, raw_bytes)

    draft = SourceJobDraft(
        raw_reference=raw_ref,
        source_key=SourceKey(provider="manual", board_id="text", source_posting_id="fx-02"),
        fetch_time=FIXED_FETCH_TIME,
        original_fields=data,
        source_mapped_fields=data["mapped_fields"],
    )

    normalizer = DefaultNormalizer(raw_reader=reader)
    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    assert posting.description_clean == data["expected"]["description_clean"]


def test_unknowns_fixture_keeps_missing_facts_unknown() -> None:
    """absent_null_empty fixture keeps missing fields unknown."""
    fixture_path = FIXTURES_DIR / "unknowns" / "absent_null_empty.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reader = InMemoryRawProvenanceReader()
    raw_ref = "memory://fixture_unknowns"
    raw_bytes = data["raw_payload"].encode("utf-8")
    reader.register(raw_ref, raw_bytes)

    draft = SourceJobDraft(
        raw_reference=raw_ref,
        source_key=SourceKey(provider="manual", board_id="text", source_posting_id="fx-03"),
        fetch_time=FIXED_FETCH_TIME,
        original_fields=data,
        source_mapped_fields=data["mapped_fields"],
    )

    normalizer = DefaultNormalizer(raw_reader=reader)
    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    assert posting.locations == []
    assert posting.workplace_type == "unknown"
    assert posting.remote_eligibility_restrictions == []
    assert posting.compensation is None
    assert posting.source_deadline_at is None

