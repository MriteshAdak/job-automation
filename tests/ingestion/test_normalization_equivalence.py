"""Tests for cross-source factual equivalence across distinct source shapes (INGEST-02-S02, S08).

Verifies that equivalent job facts represented in different source shapes
(HTML URL+text, structured CSV, and nested/API feed):
1. Yield equivalent normalized factual projections (title, company, description, locations, workplace).
2. Retain their distinct source keys, raw references, content hashes, and field provenance.
3. Verify that remote does not imply worldwide eligibility.
4. Verify that missing salary stays unknown.
5. Verify that absent deadlines are not invented.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from job_automation.contracts.enums import EmploymentType, SalaryPeriod, WorkplaceType
from job_automation.contracts.postings import NormalizedPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.normalization import (
    DefaultNormalizer,
    InMemoryRawProvenanceReader,
)
from job_automation.sources.adapters.raw import compute_content_hash


def test_cross_source_equivalence_three_shapes() -> None:
    """Manual HTML, CSV row, and API feed drafts produce equivalent core factual projections."""
    reader = InMemoryRawProvenanceReader()
    fetch_time = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    # ── Shape 1: Manual HTML (URL + Text) ──────────────────────────────────
    html_raw_bytes = (
        b"<h3>Sachbearbeiter (m/w/d)</h3>\n"
        b"<p>Unternehmen: Hansa Logistik GmbH</p>\n"
        b"<p>Standort: Hamburg, Deutschland</p>\n"
        b"<p>Wir suchen einen Sachbearbeiter fur unser Buro.</p>"
    )
    html_ref = "memory://manual_html_001"
    reader.register(html_ref, html_raw_bytes)

    draft_html = SourceJobDraft(
        raw_reference=html_ref,
        source_key=SourceKey(provider="manual", board_id="text", source_posting_id="html-001"),
        fetch_time=fetch_time,
        original_fields={"text": html_raw_bytes.decode("utf-8")},
        source_mapped_fields={
            "title": "Sachbearbeiter (m/w/d)",
            "company_name_hint": "Hansa Logistik GmbH",
            "description": "<p>Wir suchen einen Sachbearbeiter fur unser Buro.</p>",
            "source_url": "https://jobs.example.invalid/text/001",
            "locations_raw": "Hamburg, Deutschland",
            "workplace_type_raw": "vor Ort",
            "employment_type_raw": "Vollzeit",
            "compensation_raw": None,  # Missing salary
            "source_deadline_raw": None,  # Absent deadline
            "mapping_version": "1.0",
            "provenance": {
                "title": "title",
                "company_name_hint": "company",
                "description": "text",
                "source_url": "source_url",
                "locations_raw": "locations_raw",
            },
        },
    )

    # ── Shape 2: Manual CSV ────────────────────────────────────────────────
    csv_raw_bytes = (
        b"source_posting_id,source_url,title,company,text,locations_raw,workplace\r\n"
        b"0007,https://jobs.example.invalid/csv/0007,Sachbearbeiter (m/w/d),Hansa Logistik GmbH,"
        b"Wir suchen einen Sachbearbeiter fur unser Buro.,Hamburg, Deutschland,onsite\r\n"
    )
    csv_ref = "memory://manual_csv_row_0007"
    reader.register(csv_ref, csv_raw_bytes)

    draft_csv = SourceJobDraft(
        raw_reference=csv_ref,
        source_key=SourceKey(provider="manual", board_id="csv", source_posting_id="0007"),
        fetch_time=fetch_time,
        original_fields={"row_id": "0007"},
        source_mapped_fields={
            "title": "Sachbearbeiter (m/w/d)",
            "company_name_hint": "Hansa Logistik GmbH",
            "description": "Wir suchen einen Sachbearbeiter fur unser Buro.",
            "source_url": "https://jobs.example.invalid/csv/0007",
            "locations_raw": "Hamburg, Deutschland",
            "workplace_type_raw": "onsite",
            "employment_type_raw": "full-time",
            "compensation_raw": None,
            "source_deadline_raw": None,
            "mapping_version": "1.0",
            "provenance": {
                "title": "csv.title",
                "company_name_hint": "csv.company",
                "description": "csv.text",
                "source_url": "csv.source_url",
            },
        },
    )

    # ── Shape 3: JSON API Feed / Nested ATS ────────────────────────────────
    api_payload = {
        "job": {
            "title": "  Sachbearbeiter (m/w/d)  ",
            "employer": {"name": "Hansa Logistik GmbH"},
            "content": "<p>Wir suchen einen Sachbearbeiter fur unser Buro.</p>",
            "url": "https://jobs.example.invalid/feed/99",
            "location_name": "Hamburg, Deutschland",
            "workplace": "on-site",
            "type": "Vollzeit",
        }
    }
    api_raw_bytes = json.dumps(api_payload).encode("utf-8")
    api_ref = "memory://feed_job_99"
    reader.register(api_ref, api_raw_bytes)

    draft_feed = SourceJobDraft(
        raw_reference=api_ref,
        source_key=SourceKey(provider="feed", board_id="api", source_posting_id="feed-99"),
        fetch_time=fetch_time,
        original_fields=api_payload,
        source_mapped_fields={
            "title": api_payload["job"]["title"],
            "company_name_hint": api_payload["job"]["employer"]["name"],
            "description": api_payload["job"]["content"],
            "source_url": api_payload["job"]["url"],
            "locations_raw": api_payload["job"]["location_name"],
            "workplace_type_raw": api_payload["job"]["workplace"],
            "employment_type_raw": api_payload["job"]["type"],
            "compensation_raw": None,
            "source_deadline_raw": None,
            "mapping_version": "1.0",
            "provenance": {
                "title": "job.title",
                "company_name_hint": "job.employer.name",
                "description": "job.content",
                "source_url": "job.url",
            },
        },
    )

    normalizer = DefaultNormalizer(raw_reader=reader)

    postings = []
    for d in [draft_html, draft_csv, draft_feed]:
        p, issues = normalizer.normalize(d)
        assert p is not None, f"Failed normalization for {d.source_key}: {issues}"
        postings.append(p)

    p_html, p_csv, p_feed = postings

    # ── Verification 1: Equivalent factual projections ─────────────────────
    for p in [p_html, p_csv, p_feed]:
        assert p.title == "Sachbearbeiter (m/w/d)"
        assert p.company_name_hint == "Hansa Logistik GmbH"
        assert p.description_clean == "Wir suchen einen Sachbearbeiter fur unser Buro."
        assert len(p.locations) == 1
        assert p.locations[0].city == "Hamburg"
        assert p.locations[0].country == "DE"
        assert p.workplace_type == WorkplaceType.ONSITE
        assert p.employment_type == EmploymentType.FULL_TIME

        # Verification 3: Missing salary stays unknown (None)
        assert p.compensation is None

        # Verification 4: Absent deadline is not invented (None)
        assert p.source_deadline_at is None

    # ── Verification 2: Provenance and identity separation ──────────────────
    # Source keys remain distinct
    assert p_html.source_key.provider == "manual"
    assert p_html.source_key.board_id == "text"

    assert p_csv.source_key.provider == "manual"
    assert p_csv.source_key.board_id == "csv"
    assert p_csv.source_key.source_posting_id == "0007"  # Exact string ID preserved

    assert p_feed.source_key.provider == "feed"
    assert p_feed.source_key.board_id == "api"

    # Raw references and hashes remain distinct
    assert p_html.raw_reference == html_ref
    assert p_csv.raw_reference == csv_ref
    assert p_feed.raw_reference == api_ref

    assert p_html.raw_content_hash == compute_content_hash(html_raw_bytes)
    assert p_csv.raw_content_hash == compute_content_hash(csv_raw_bytes)
    assert p_feed.raw_content_hash == compute_content_hash(api_raw_bytes)

    # Field provenance points to source-specific paths
    assert p_html.field_provenance["description_clean"] == "text"
    assert p_csv.field_provenance["description_clean"] == "csv.text"
    assert p_feed.field_provenance["description_clean"] == "job.content"


def test_remote_does_not_imply_worldwide_eligibility() -> None:
    """A remote job posting retains an empty/unknown restrictions set without inferring worldwide."""
    reader = InMemoryRawProvenanceReader()
    raw = b"remote job advert"
    ref = "memory://remote_job"
    reader.register(ref, raw)

    draft = SourceJobDraft(
        raw_reference=ref,
        source_key=SourceKey(provider="manual", board_id="text", source_posting_id="rem-1"),
        fetch_time=datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc),
        original_fields={},
        source_mapped_fields={
            "title": "Distributed Systems Engineer",
            "company_name_hint": "Global Tech",
            "description": "Full-time remote position working on cloud systems.",
            "source_url": "https://example.com/job/remote",
            "workplace_type_raw": "remote",
            "remote_eligibility_restrictions": None,  # No restrictions stated
            "mapping_version": "1.0",
        },
    )

    normalizer = DefaultNormalizer(raw_reader=reader)
    p, issues = normalizer.normalize(draft)

    assert p is not None
    assert p.workplace_type == WorkplaceType.REMOTE
    assert p.remote_eligibility_restrictions == []
    # Does NOT contain worldwide or any invented country
    assert "worldwide" not in p.remote_eligibility_restrictions
    assert "DE" not in p.remote_eligibility_restrictions

