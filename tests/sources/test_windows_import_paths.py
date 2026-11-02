"""Native Windows path, encoding, and file-handle verification (SOURCE-02-S08).

Tests:
- Paths with spaces and German umlauts (ä, ö, ü, ß).
- Windows CRLF line endings and UTF-8 BOM.
- Explicit base path resolution independent of process working directory.
- Immediate handle release enabling file renaming/reopening after import.
- URL strings never passed through filesystem path normalization.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.manual_csv import ManualCsvAdapter
from job_automation.sources.adapters.manual_text import ManualTextAdapter
from job_automation.sources.adapters.raw import InMemoryRawCaptureSink
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveRequestPolicy,
    EffectiveSource,
    InventoryScope,
)


@pytest.fixture
def windows_effective_source() -> EffectiveSource:
    config = SourceConfig(
        source_key="windows_test_source",
        provider="manual",
        board_id="win_inbox",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="manual://windows/inbox",
        access_rules=json.dumps(
            {
                "status": "permitted",
                "reviewed_at": "2026-10-28T00:00:00Z",
                "evidence_ref": "win-test",
                "permitted_methods": ["manual_import"],
            }
        ),
        attribution_rules="none_required",
        enabled=True,
        inventory_semantics=InventorySemantics.SEARCH_RESULTS,
    )
    return EffectiveSource(
        config=config,
        access_review=AccessReview(
            status=AccessReviewStatus.PERMITTED,
            reviewed_at="2026-10-28T00:00:00Z",
            evidence_ref="win-test",
            permitted_methods=[AcquisitionMethod.MANUAL_IMPORT],
        ),
        attribution_review=AttributionReview(status=AttributionStatus.NONE_REQUIRED),
        request_policy=EffectiveRequestPolicy(),
        inventory_scope=InventoryScope(
            scope_id="scope-v1:windows_test",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="win_inbox",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://windows/inbox",
        ),
    )


def test_windows_text_import_with_spaces_umlauts_and_handle_release(
    tmp_path: Path,
    windows_effective_source: EffectiveSource,
) -> None:
    # Directory with spaces and umlauts
    work_dir = tmp_path / "Job Test Verzeichnis ä ö ü"
    work_dir.mkdir()

    file_name = "Stellen Prüfung ä.txt"
    file_path = work_dir / file_name
    file_path.write_text(
        "Senior Backend Entwickler (m/w/d)\r\nStandort: München / Berlin\r\nVergütung: 80.000 €\r\n",
        encoding="utf-8",
    )

    sink = InMemoryRawCaptureSink()
    # Call adapter using relative path with explicit input_base_path
    adapter = ManualTextAdapter(
        effective_source=windows_effective_source,
        capture_sink=sink,
        source_url="https://jobs.example.invalid/vacancies/win_01",
        text_path=file_name,
        input_base_path=work_dir,
    )

    page = adapter.fetch_page(windows_effective_source.config)
    assert len(page.items) == 1
    assert "Senior Backend Entwickler" in page.items[0].raw_payload
    assert "80.000 €" in page.items[0].raw_payload

    # Demonstrate handle release on native Windows: renaming the file succeeds immediately!
    renamed_path = work_dir / "Stellen Prüfung umbenannt.txt"
    file_path.rename(renamed_path)
    assert renamed_path.is_file()
    assert not file_path.exists()


def test_windows_csv_import_with_crlf_bom_and_independent_cwd(
    tmp_path: Path,
    windows_effective_source: EffectiveSource,
) -> None:
    work_dir = tmp_path / "CSV Daten Ordner Größe"
    work_dir.mkdir()

    csv_name = "Stellen Übersicht ä.csv"
    csv_path = work_dir / csv_name

    # Write UTF-8 with BOM and CRLF line endings
    csv_content = (
        "\ufeffsource_url,title,company,text\r\n"
        "https://jobs.example.invalid/win/1,Entwickler 1,Firma A,Erste Beschreibung mit Umlaut ä\r\n"
        "https://jobs.example.invalid/win/2,Entwickler 2,Firma B,Zweite Beschreibung mit Umlaut ö\r\n"
    )
    csv_path.write_bytes(csv_content.encode("utf-8"))

    sink = InMemoryRawCaptureSink()

    # Change process working directory to a different folder to prove no cwd dependency
    other_dir = tmp_path / "Anderer Arbeitsbereich"
    other_dir.mkdir()
    old_cwd = os.getcwd()
    try:
        os.chdir(other_dir)
        adapter = ManualCsvAdapter(
            effective_source=windows_effective_source,
            capture_sink=sink,
            csv_path=csv_name,
            input_base_path=work_dir,
        )
        page = adapter.fetch_page(windows_effective_source.config)
        assert len(page.items) == 2
        assert page.exhausted
        assert "Erste Beschreibung mit Umlaut ä" in page.items[0].raw_payload
        assert "Zweite Beschreibung mit Umlaut ö" in page.items[1].raw_payload
    finally:
        os.chdir(old_cwd)

    # Demonstrate handle release: file can be immediately overwritten or deleted
    csv_path.unlink()
    assert not csv_path.exists()


def test_windows_url_not_treated_as_filesystem_path(windows_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    # URL contains forward slashes, query parameters, and fragments:
    # Must NEVER be mangled by os.path.normpath or backslash substitution!
    url_with_slashes = "https://jobs.example.invalid/vacancies/search?role=dev#section"
    adapter = ManualTextAdapter(
        effective_source=windows_effective_source,
        capture_sink=sink,
        source_url=url_with_slashes,
        text="Sample text",
    )
    page = adapter.fetch_page(windows_effective_source.config)
    assert len(page.items) == 1
    draft_res = adapter.draft_posting(page.items[0])
    assert draft_res.draft is not None
    assert draft_res.draft.source_mapped_fields["source_url"] == url_with_slashes
    assert "\\" not in draft_res.draft.source_mapped_fields["source_url"]

