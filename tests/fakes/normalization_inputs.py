"""Test helper fakes and input builders for normalization tests (INGEST-02)."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.postings import SourceJobDraft
from job_automation.contracts.primitives import ContentHash, SourceKey, UtcDatetime
from job_automation.ingestion.normalization.ports import InMemoryRawProvenanceReader
from job_automation.sources.adapters.raw import compute_content_hash

FIXED_FETCH_TIME = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)


def create_sample_draft(
    raw_reference: str = "memory://sample_raw_1",
    raw_bytes: bytes = b"sample raw job content",
    source_key: SourceKey | None = None,
    fetch_time: UtcDatetime | None = None,
    title: str | None = "Sachbearbeiter (m/w/d)",
    company_name_hint: str | None = "Beispiel GmbH",
    description: str | None = "<p>Wir suchen einen <strong>Sachbearbeiter</strong>.</p>",
    source_url: str | None = "https://example.com/jobs/1",
    application_url: str | None = None,
    locations_raw: Any = "Berlin, Deutschland",
    workplace_type_raw: Any = "hybrid",
    remote_eligibility_restrictions: Any = None,
    employment_type_raw: Any = "Vollzeit",
    compensation_raw: Any = "60.000 - 75.000 EUR brutto/Jahr",
    source_published_raw: Any = "2026-10-28T09:30:00+01:00",
    source_updated_raw: Any = None,
    source_deadline_raw: Any = None,
    advert_language: str | None = "de",
    mapping_version: str = "1.0",
    reader: InMemoryRawProvenanceReader | None = None,
) -> SourceJobDraft:
    """Create a valid synthetic SourceJobDraft and register its bytes in reader."""
    s_key = source_key or SourceKey(
        provider="manual",
        board_id="default",
        source_posting_id="sample-001",
    )
    f_time = fetch_time or FIXED_FETCH_TIME
    content_hash = compute_content_hash(raw_bytes)

    if reader is not None:
        reader.register(raw_reference, raw_bytes, content_hash)

    mapped_fields: dict[str, Any] = {
        "title": title,
        "company_name_hint": company_name_hint,
        "description": description,
        "source_url": source_url,
        "application_url": application_url,
        "locations_raw": locations_raw,
        "workplace_type_raw": workplace_type_raw,
        "remote_eligibility_restrictions": remote_eligibility_restrictions,
        "employment_type_raw": employment_type_raw,
        "compensation_raw": compensation_raw,
        "source_published_raw": source_published_raw,
        "source_updated_raw": source_updated_raw,
        "source_deadline_raw": source_deadline_raw,
        "advert_language": advert_language,
        "mapping_version": mapping_version,
        "provenance": {
            "title": "title",
            "company_name_hint": "company",
            "description": "description",
            "source_url": "source_url",
            "application_url": "application_url",
            "locations_raw": "locations_raw",
            "workplace_type_raw": "workplace_type_raw",
            "employment_type_raw": "employment_type_raw",
            "compensation_raw": "compensation_raw",
            "source_published_raw": "source_published_raw",
            "source_deadline_raw": "source_deadline_raw",
        },
    }

    original_fields = {
        "title": title,
        "company": company_name_hint,
        "raw_content_hash": content_hash,
    }

    return SourceJobDraft(
        raw_reference=raw_reference,
        source_key=s_key,
        fetch_time=f_time,
        original_fields=original_fields,
        source_mapped_fields=mapped_fields,
    )

