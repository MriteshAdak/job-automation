"""Shared adapter conformance verification (SOURCE-02-S07).

Demonstrates that ScriptedPaginatedFakeAdapter, ManualTextAdapter, and ManualCsvAdapter
satisfy the identical Adapter interface Protocol and pagination invariants without
adapter-specific branching.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    RecordIssue,
)
from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.interfaces import Adapter
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
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
from tests.fakes.paginated_adapter import ScriptedPaginatedFakeAdapter


def harness_collect_adapter(
    adapter: Adapter,
    config: SourceConfig,
    max_pages: int = 10,
) -> tuple[list[SourceJobDraft], list[RecordIssue], bool]:
    """Unified consumer harness calling only the shared Adapter interface."""
    drafts: list[SourceJobDraft] = []
    all_issues: list[RecordIssue] = []
    continuation: Continuation | None = None
    exhausted = False

    for _ in range(max_pages):
        page: AdapterPage = adapter.fetch_page(config, continuation=continuation)
        all_issues.extend(page.issues)
        for raw in page.items:
            res = adapter.draft_posting(raw)
            all_issues.extend(res.issues)
            if res.draft is not None:
                drafts.append(res.draft)

        if page.exhausted:
            exhausted = True
            break
        continuation = page.continuation_out
        if continuation is None:
            break

    return drafts, all_issues, exhausted


def build_fake_paginated_adapter() -> tuple[Adapter, SourceConfig]:
    config = SourceConfig(
        source_key="fake_paginated_source",
        provider="fake_provider",
        board_id="board_1",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://api.fake.invalid/jobs",
        access_rules="{}",
        attribution_rules="none_required",
        enabled=True,
        inventory_semantics=InventorySemantics.FILTERED_FEED,
    )
    sk1 = SourceKey(provider="fake_provider", board_id="board_1", source_posting_id="p1_01")
    sk2 = SourceKey(provider="fake_provider", board_id="board_1", source_posting_id="p1_02")
    sk3 = SourceKey(provider="fake_provider", board_id="board_1", source_posting_id="p3_01")

    raw1 = RawPosting(
        raw_payload_ref="ref/p1_01",
        raw_content_hash="sha256:" + "1" * 64,
        source_key=sk1,
        fetch_time="2026-10-28T09:00:00Z",
        raw_payload="{\"title\": \"Job 1\"}",
    )
    raw2 = RawPosting(
        raw_payload_ref="ref/p1_02",
        raw_content_hash="sha256:" + "2" * 64,
        source_key=sk2,
        fetch_time="2026-10-28T09:00:00Z",
        raw_payload="{\"title\": \"Job 2\"}",
    )
    raw3 = RawPosting(
        raw_payload_ref="ref/p3_01",
        raw_content_hash="sha256:" + "3" * 64,
        source_key=sk3,
        fetch_time="2026-10-28T09:02:00Z",
        raw_payload="{\"title\": \"Job 3\"}",
    )

    page1 = AdapterPage(
        items=[raw1, raw2],
        continuation_out=Continuation(
            kind="cursor",
            value="page_2",
            source_key="fake_paginated_source",
            scope_id="scope-fake",
            adapter_name="fake",
        ),
        exhausted=False,
    )
    page2 = AdapterPage(
        items=[],  # Empty intermediate page with continuation
        continuation_out=Continuation(
            kind="cursor",
            value="page_3",
            source_key="fake_paginated_source",
            scope_id="scope-fake",
            adapter_name="fake",
        ),
        exhausted=False,
    )
    page3 = AdapterPage(
        items=[raw3],
        continuation_out=None,
        exhausted=True,
    )

    pages = {None: page1, "page_2": page2, "page_3": page3}
    adapter = ScriptedPaginatedFakeAdapter(pages=pages, expected_source_key="fake_paginated_source")
    return adapter, config


def build_manual_text_adapter() -> tuple[Adapter, SourceConfig]:
    config = SourceConfig(
        source_key="manual_text_source",
        provider="manual",
        board_id="inbox",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="manual://inbox",
        access_rules="{}",
        attribution_rules="none_required",
        enabled=True,
        inventory_semantics=InventorySemantics.SEARCH_RESULTS,
    )
    eff_source = EffectiveSource(
        config=config,
        access_review=AccessReview(
            status=AccessReviewStatus.PERMITTED,
            reviewed_at="2026-10-28T00:00:00Z",
            evidence_ref="test",
            permitted_methods=[AcquisitionMethod.MANUAL_IMPORT],
        ),
        attribution_review=AttributionReview(status=AttributionStatus.NONE_REQUIRED),
        request_policy=EffectiveRequestPolicy(),
        inventory_scope=InventoryScope(
            scope_id="scope-text",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="inbox",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://inbox",
        ),
    )
    sink = InMemoryRawCaptureSink()
    adapter = ManualTextAdapter(
        effective_source=eff_source,
        capture_sink=sink,
        source_url="https://jobs.example.invalid/vacancies/001",
        text="Software Engineer in Berlin gesucht.",
        title="Software Engineer",
        company="Sample AG",
    )
    return adapter, config


def build_manual_csv_adapter() -> tuple[Adapter, SourceConfig]:
    config = SourceConfig(
        source_key="manual_csv_source",
        provider="manual",
        board_id="inbox_csv",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="manual://csv",
        access_rules="{}",
        attribution_rules="none_required",
        enabled=True,
        inventory_semantics=InventorySemantics.SEARCH_RESULTS,
    )
    eff_source = EffectiveSource(
        config=config,
        access_review=AccessReview(
            status=AccessReviewStatus.PERMITTED,
            reviewed_at="2026-10-28T00:00:00Z",
            evidence_ref="test",
            permitted_methods=[AcquisitionMethod.MANUAL_IMPORT],
        ),
        attribution_review=AttributionReview(status=AttributionStatus.NONE_REQUIRED),
        request_policy=EffectiveRequestPolicy(),
        inventory_scope=InventoryScope(
            scope_id="scope-csv",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="inbox_csv",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://csv",
        ),
    )
    csv_data = b"""source_url,title,company,text
https://jobs.example.invalid/csv/1,Dev 1,Corp 1,Text 1
https://jobs.example.invalid/csv/2,Dev 2,Corp 2,Text 2
"""
    sink = InMemoryRawCaptureSink()
    adapter = ManualCsvAdapter(
        effective_source=eff_source,
        capture_sink=sink,
        csv_bytes=csv_data,
        page_size=1,  # Paged across 2 pages
    )
    return adapter, config


def build_arbeitnow_conformance_adapter() -> tuple[Adapter, SourceConfig]:
    from tests.sources.arbeitnow_helpers import (
        FakeTransport,
        build_adapter,
        build_arbeitnow_config,
        load_fixture,
    )
    from job_automation.sources.adapters.arbeitnow import build_page_url

    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, load_fixture("page_1.json"))
    transport.add(build_page_url(2), 200, {}, load_fixture("page_2.json"))
    transport.add(build_page_url(3), 200, {}, load_fixture("page_terminal.json"))

    adapter, _ = build_adapter(transport=transport)
    config = build_arbeitnow_config()
    return adapter, config


@pytest.mark.parametrize(
    "adapter_builder,expected_count",
    [
        (build_fake_paginated_adapter, 3),
        (build_manual_text_adapter, 1),
        (build_manual_csv_adapter, 2),
        (build_arbeitnow_conformance_adapter, 4),
    ],
)
def test_adapter_shared_interface_conformance(adapter_builder: object, expected_count: int) -> None:
    adapter, config = adapter_builder()
    drafts, issues, exhausted = harness_collect_adapter(adapter, config)

    assert isinstance(adapter, Adapter)
    assert len(drafts) == expected_count
    assert exhausted
    for draft in drafts:
        assert isinstance(draft, SourceJobDraft)
        assert draft.raw_reference
        assert draft.source_key
        assert draft.source_mapped_fields["description"]

