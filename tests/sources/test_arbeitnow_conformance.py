"""Shared consumer boundary, failure isolation, and protocol conformance tests (SOURCE-03-S06)."""

from __future__ import annotations

import pytest

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.interfaces import Adapter
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter, build_page_url
from tests.sources.arbeitnow_helpers import (
    FakeTransport,
    build_adapter,
    build_arbeitnow_config,
    load_fixture,
)


def _harness_collect(
    adapter: Adapter,
    config: SourceConfig,
    max_pages: int = 10,
) -> tuple[list[SourceJobDraft], list[RecordIssue], bool, list[AdapterPage]]:
    """Consumer harness calling ONLY the shared Adapter interface boundary."""
    drafts: list[SourceJobDraft] = []
    all_issues: list[RecordIssue] = []
    pages: list[AdapterPage] = []
    continuation: Continuation | None = None
    exhausted = False

    for _ in range(max_pages):
        page = adapter.fetch_page(config, continuation=continuation)
        pages.append(page)
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

    return drafts, all_issues, exhausted, pages


def test_arbeitnow_adapter_satisfies_protocol() -> None:
    adapter, _ = build_adapter()
    assert isinstance(adapter, Adapter)


def test_three_page_traversal_to_exhaustion() -> None:
    p1 = load_fixture("page_1.json")  # 2 jobs, next=2
    p2 = load_fixture("page_2.json")  # 1 job, next=3
    p3 = load_fixture("page_terminal.json")  # 1 job, next=null

    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, p1)
    transport.add(build_page_url(2), 200, {}, p2)
    transport.add(build_page_url(3), 200, {}, p3)

    adapter, _ = build_adapter(transport=transport)
    config = build_arbeitnow_config()

    drafts, issues, exhausted, pages = _harness_collect(adapter, config, max_pages=10)

    assert len(pages) == 3
    assert exhausted
    # 2 from p1 + 1 from p2 + 1 from p3 = 4 drafts total
    assert len(drafts) == 4
    for draft in drafts:
        assert isinstance(draft, SourceJobDraft)
        assert draft.raw_reference
        assert draft.source_key
        assert draft.source_mapped_fields["description"]


def test_page_1_success_then_page_2_failure_preserves_page_1_data() -> None:
    p1 = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, p1)
    # page 2 returns 429
    transport.add(build_page_url(2), 429, {"retry-after": "60"}, b'{"error":"rate_limit"}')

    adapter, _ = build_adapter(transport=transport)
    config = build_arbeitnow_config()

    drafts, issues, exhausted, pages = _harness_collect(adapter, config, max_pages=10)

    assert len(pages) == 2
    assert not exhausted  # Traversal stopped by error, not complete
    assert len(drafts) == 2  # Page 1 drafts are intact!
    assert pages[1].page_error is not None
    assert pages[1].page_error.category == ErrorCategory.RATE_LIMIT


def test_page_with_mixed_valid_and_invalid_records_isolates_errors() -> None:
    wrong_types = load_fixture("wrong_types.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, wrong_types)

    adapter, _ = build_adapter(transport=transport)
    config = build_arbeitnow_config()

    drafts, issues, exhausted, pages = _harness_collect(adapter, config, max_pages=1)

    assert len(pages) == 1
    # 1 valid record drafted, 1 invalid record produced issue
    assert len(drafts) == 1
    assert drafts[0].source_key.source_posting_id == "ok-slug-0002"
    assert any(iss.code == "invalid_slug_type" for iss in issues)


def test_all_output_structures_conform_to_contract_models() -> None:
    p1 = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, p1)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    # Check Pydantic validation
    assert isinstance(page, AdapterPage)
    assert page.continuation_out is not None
    assert isinstance(page.continuation_out, Continuation)

    for item in page.items:
        assert isinstance(item, RawPosting)
        res = adapter.draft_posting(item)
        assert isinstance(res, DraftResult)
        if res.draft is not None:
            assert isinstance(res.draft, SourceJobDraft)

