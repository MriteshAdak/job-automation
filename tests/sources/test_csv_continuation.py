"""Tests for CSV pagination, continuation, and input hash binding (SOURCE-02-S05)."""

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

CSV_CONTENT_2_ROWS = b"""source_url,title,company,text
https://jobs.example.invalid/job1,Job 1,Corp 1,Description 1
https://jobs.example.invalid/job2,Job 2,Corp 2,Description 2
"""


@pytest.fixture
def manual_effective_source() -> EffectiveSource:
    config = SourceConfig(
        source_key="csv_paginated_source",
        provider="manual",
        board_id="csv_paging",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="manual://csv/paging",
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
            scope_id="scope-v1:csv_paging_test",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="csv_paging",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://csv/paging",
        ),
    )


def test_csv_pagination_and_resumption(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    # page_size=1 ensures 2 pages for 2 rows
    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_bytes=CSV_CONTENT_2_ROWS,
        page_size=1,
    )

    # Page 1
    page1 = adapter.fetch_page(manual_effective_source.config)
    assert len(page1.items) == 1
    assert not page1.exhausted
    assert page1.continuation_out is not None
    assert page1.continuation_out.value == "2"

    # Page 2 using continuation_out from page 1
    page2 = adapter.fetch_page(manual_effective_source.config, continuation=page1.continuation_out)
    assert len(page2.items) == 1
    assert page2.exhausted
    assert page2.continuation_out is None

    # Verify both postings are distinct
    assert page1.items[0].source_key.source_posting_id != page2.items[0].source_key.source_posting_id


def test_csv_continuation_input_stale_detected(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter1 = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_bytes=CSV_CONTENT_2_ROWS,
        page_size=1,
    )
    page1 = adapter1.fetch_page(manual_effective_source.config)
    assert page1.continuation_out is not None

    # New adapter instance with changed CSV content
    changed_bytes = CSV_CONTENT_2_ROWS + b"https://jobs.example.invalid/job3,Job 3,Corp 3,Desc 3\n"
    adapter2 = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_bytes=changed_bytes,
        page_size=1,
    )

    # Attempting to resume with old continuation token fails because input hash changed!
    page_resume = adapter2.fetch_page(manual_effective_source.config, continuation=page1.continuation_out)
    assert len(page_resume.items) == 0
    assert page_resume.page_error is not None
    assert page_resume.page_error.details is not None
    assert page_resume.page_error.details.get("code") == "invalid_continuation"
    assert "input has changed" in page_resume.page_error.message
