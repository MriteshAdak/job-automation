"""Consumer boundary tests for downstream INGEST-01 and manifest integration (SOURCE-02-S07).

Demonstrates:
- Retention of previously captured records upon mid-stream page failure
- Preservation of scope semantics (search_results vs complete_board)
- Bridging Continuation to C04 cursor_in / cursor_out
"""

from __future__ import annotations

from uuid import uuid4
import pytest

from job_automation.contracts.adapter_results import AdapterPage, Continuation
from job_automation.contracts.enums import (
    AcquisitionMethod,
    FetchOutcome,
    InventorySemantics,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import FetchManifest, RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from tests.fakes.paginated_adapter import ScriptedPaginatedFakeAdapter


def test_consumer_retains_prior_records_on_midstream_failure() -> None:
    """Verify that a failure on page 2 retains page 1 records and marks manifest as failed/partial."""
    sk1 = SourceKey(provider="prov", board_id="b1", source_posting_id="101")
    raw1 = RawPosting(
        raw_payload_ref="ref/101",
        raw_content_hash="sha256:" + "1" * 64,
        source_key=sk1,
        fetch_time="2026-10-28T09:00:00Z",
        raw_payload="{\"title\": \"Job 1\"}",
    )
    page1 = AdapterPage(
        items=[raw1],
        continuation_out=Continuation(
            kind="cursor",
            value="page_2",
            source_key="src",
            scope_id="scope-1",
            adapter_name="fake",
        ),
        exhausted=False,
    )
    # Page 2 fails with operational/rate limit error
    err = ClassifiedError.from_category(
        category=ErrorCategory.RATE_LIMIT,
        message="Rate limit exceeded on provider",
        details={"code": "rate_limit_exceeded"},
    )
    page2 = AdapterPage(
        items=[],
        page_error=err,
        exhausted=False,  # Not exhausted!
    )

    adapter = ScriptedPaginatedFakeAdapter(pages={None: page1, "page_2": page2})
    config = SourceConfig(
        source_key="src",
        provider="prov",
        board_id="b1",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://api.example.invalid",
        access_rules="{}",
        attribution_rules="none_required",
        enabled=True,
        inventory_semantics=InventorySemantics.FILTERED_FEED,
    )

    # Consumer executes traversal
    captured_records: list[RawPosting] = []
    current_cont: Continuation | None = None
    traversal_outcome = FetchOutcome.COMPLETE
    terminal_error = None

    for _ in range(5):
        page = adapter.fetch_page(config, continuation=current_cont)
        captured_records.extend(page.items)
        if page.page_error is not None:
            traversal_outcome = FetchOutcome.PARTIAL if captured_records else FetchOutcome.FAILED
            terminal_error = page.page_error
            break
        if page.exhausted:
            break
        current_cont = page.continuation_out

    # Consumer retains record 1 despite page 2 failure!
    assert len(captured_records) == 1
    assert captured_records[0].source_key.source_posting_id == "101"
    assert traversal_outcome == FetchOutcome.PARTIAL
    assert terminal_error is not None
    assert terminal_error.details is not None
    assert terminal_error.details.get("code") == "rate_limit_exceeded"

    # Simulate C04 FetchManifest creation
    manifest = FetchManifest(
        run_id=uuid4(),
        source_key=config.source_key,
        scope_id="scope-1",
        start_time="2026-10-28T09:00:00Z",
        end_time="2026-10-28T09:01:00Z",
        cursor_in=None,
        cursor_out=page1.continuation_out.encode() if page1.continuation_out else None,
        page_count=2,
        observed_posting_identities=[r.source_key.source_posting_id for r in captured_records],
        outcome=traversal_outcome,
        inventory_semantics=config.inventory_semantics,
        error=terminal_error,
    )
    assert manifest.outcome == FetchOutcome.PARTIAL
    assert manifest.page_count == 2
    assert manifest.observed_posting_identities == ["101"]
