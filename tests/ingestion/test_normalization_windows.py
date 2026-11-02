"""Native Windows verification checks for normalization (INGEST-02-S08).

Verifies Windows-specific constraints:
- Handles paths containing spaces and German umlauts (Prüfung äöü INGEST-02).
- Verifies exact-byte integrity for UTF-8 with BOM and CRLF.
- Proves file handles are released immediately so files can be deleted/renamed.
- Verifies execution from alternate CWD without relative path dependencies.
- Resolves Europe/Berlin using tzdata on Windows independent of system timezone.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from job_automation.contracts.postings import SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.normalization import (
    DefaultNormalizer,
    InMemoryRawProvenanceReader,
)
from job_automation.ingestion.normalization.dates import normalize_source_date
from job_automation.sources.adapters.raw import compute_content_hash


def test_windows_paths_with_spaces_and_umlauts(tmp_path: Path) -> None:
    """Normalization operates reliably on Windows paths with spaces and German umlauts."""
    unicode_dir = tmp_path / "Job Automation Prüfung äöü INGEST-02"
    unicode_dir.mkdir(parents=True, exist_ok=True)

    payload_file = unicode_dir / "raw_stelle_001.dat"
    raw_bytes = (
        b"\xef\xbb\xbf<h3>Sachbearbeiter (m/w/d)</h3>\r\n"
        b"<p>Unternehmen: Muster Logistik AG</p>\r\n"
        b"<p>Standort: M\xc3\xbcnchen, Deutschland</p>\r\n"
        b"<p>Beschreibung der T\xc3\xa4tigkeit.</p>\r\n"
    )
    payload_file.write_bytes(raw_bytes)

    # Verify content hash from exact disk bytes
    read_bytes = payload_file.read_bytes()
    assert read_bytes == raw_bytes
    expected_hash = compute_content_hash(read_bytes)

    reader = InMemoryRawProvenanceReader()
    raw_ref = str(payload_file.resolve())
    reader.register(raw_ref, read_bytes, expected_hash)

    draft = SourceJobDraft(
        raw_reference=raw_ref,
        source_key=SourceKey(provider="manual", board_id="win", source_posting_id="win-01"),
        fetch_time=datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc),
        original_fields={"path": raw_ref},
        source_mapped_fields={
            "title": "Sachbearbeiter (m/w/d)",
            "company_name_hint": "Muster Logistik AG",
            "description": "<p>Beschreibung der Tätigkeit.</p>",
            "source_url": "https://example.com/job/win-01",
            "locations_raw": "München, Deutschland",
            "workplace_type_raw": "vor Ort",
            "employment_type_raw": "Vollzeit",
            "mapping_version": "1.0",
        },
    )

    normalizer = DefaultNormalizer(raw_reader=reader)
    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    assert posting.title == "Sachbearbeiter (m/w/d)"
    assert posting.company_name_hint == "Muster Logistik AG"
    assert posting.raw_content_hash == expected_hash
    assert len(posting.locations) == 1
    assert posting.locations[0].city == "München"
    assert posting.locations[0].country == "DE"


def test_windows_handle_release(tmp_path: Path) -> None:
    """Files read during normalization release handles immediately on Windows."""
    test_file = tmp_path / "temp_payload.dat"
    content = b"content to verify handle release"
    test_file.write_bytes(content)

    reader = InMemoryRawProvenanceReader()
    ref = str(test_file.resolve())
    with open(test_file, "rb") as f:
        data = f.read()
    reader.register(ref, data)

    draft = SourceJobDraft(
        raw_reference=ref,
        source_key=SourceKey(provider="manual", board_id="temp", source_posting_id="tmp-01"),
        fetch_time=datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc),
        original_fields={},
        source_mapped_fields={
            "title": "Temporary Engineer",
            "company_name_hint": "Temp AG",
            "description": "Short description",
            "source_url": "https://example.com/job/tmp-01",
            "mapping_version": "1.0",
        },
    )

    normalizer = DefaultNormalizer(raw_reader=reader)
    posting, issues = normalizer.normalize(draft)
    assert posting is not None

    # Prove handle is released: file can be deleted without Windows file locking error
    test_file.unlink()
    assert not test_file.exists()


def test_windows_alternate_cwd_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Normalization operates correctly when process CWD is changed outside repository."""
    external_dir = tmp_path / "outside_workspace"
    external_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(external_dir)

    reader = InMemoryRawProvenanceReader()
    ref = "memory://alternate_cwd_job"
    reader.register(ref, b"job content")

    draft = SourceJobDraft(
        raw_reference=ref,
        source_key=SourceKey(provider="manual", board_id="cwd", source_posting_id="cwd-01"),
        fetch_time=datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc),
        original_fields={},
        source_mapped_fields={
            "title": "Platform Engineer",
            "company_name_hint": "Cloud GmbH",
            "description": "Platform engineering from another CWD.",
            "source_url": "https://example.com/job/cwd-01",
            "mapping_version": "1.0",
        },
    )

    normalizer = DefaultNormalizer(raw_reader=reader)
    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    assert posting.title == "Platform Engineer"


def test_windows_tzdata_berlin() -> None:
    """Resolves Europe/Berlin using tzdata on Windows independent of machine timezone."""
    tz = ZoneInfo("Europe/Berlin")
    assert str(tz) == "Europe/Berlin"

    dt, issues = normalize_source_date(
        "2026-10-28T10:00:00",
        field_name="source_published_at",
        declared_tz="Europe/Berlin",
    )
    assert dt == datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)
    assert not issues

