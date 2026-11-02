"""Tests for ManualCsvAdapter (SOURCE-02-S05)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.manual_csv import ManualCsvAdapter
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

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sources" / "manual" / "csv"


@pytest.fixture
def manual_effective_source() -> EffectiveSource:
    config = SourceConfig(
        source_key="manual_csv_source",
        provider="manual",
        board_id="csv_import",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="manual://csv/file",
        access_rules=json.dumps(
            {
                "status": "permitted",
                "reviewed_at": "2026-10-28T00:00:00Z",
                "evidence_ref": "csv-terms",
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
            evidence_ref="csv-terms",
            permitted_methods=[AcquisitionMethod.MANUAL_IMPORT],
        ),
        attribution_review=AttributionReview(status=AttributionStatus.NONE_REQUIRED),
        request_policy=EffectiveRequestPolicy(),
        inventory_scope=InventoryScope(
            scope_id="scope-v1:manual_csv_test",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="csv_import",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://csv/file",
        ),
    )


def test_manual_csv_adapter_valid_jobs(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="valid_jobs.csv",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 2
    assert page.exhausted
    assert page.continuation_out is None
    assert page.items[0].source_key.source_posting_id == "0007"
    assert page.items[1].source_key.source_posting_id == "0008"

    # Draft both postings
    draft_1 = adapter.draft_posting(page.items[0])
    assert draft_1.draft is not None
    assert draft_1.draft.source_mapped_fields["title"] == "Senior Python Developer"
    assert draft_1.draft.source_mapped_fields["company_name_hint"] == "Tech GmbH"


def test_manual_csv_adapter_semicolon(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="valid_semicolon.csv",
        input_base_path=FIXTURES_DIR,
        delimiter=";",
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 2
    assert page.exhausted
    assert page.items[0].source_key.source_posting_id == "42"
    assert page.items[1].source_key.source_posting_id == "43"


def test_manual_csv_adapter_multiline_quoted(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="multiline_quoted.csv",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 2
    raw_payload_dict = json.loads(page.items[0].raw_payload)
    assert "Ihre Aufgaben:\n- Frontend in React" in raw_payload_dict["text"]


def test_manual_csv_adapter_mixed_errors_isolation(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="mixed_errors.csv",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    # Row 1 and Row 3 are valid -> 2 accepted items
    assert len(page.items) == 2
    # Row 2 had bad URL -> 1 issue locating row 2
    error_issues = [iss for iss in page.issues if iss.severity == "error"]
    assert len(error_issues) == 1
    assert error_issues[0].record_index == 2
    assert "invalid_source_url" in error_issues[0].code


def test_manual_csv_adapter_missing_required_column(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="invalid_missing_columns.csv",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 0
    assert page.page_error is not None
    assert page.page_error.details is not None
    assert page.page_error.details.get("code") == "missing_required_column"


def test_manual_csv_adapter_duplicate_headers(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="invalid_duplicate_headers.csv",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 0
    assert page.page_error is not None
    assert page.page_error.details is not None
    assert page.page_error.details.get("code") == "duplicate_csv_header"


def test_manual_csv_adapter_bom_file(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="bom_jobs.csv",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 1
    assert page.items[0].source_key.source_posting_id.startswith("url-v1:")


def test_manual_csv_adapter_rejects_xlsx_format(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path="spreadsheet.xlsx",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 0
    assert page.page_error is not None
    assert page.page_error.details is not None
    assert page.page_error.details.get("code") == "unsupported_format"
