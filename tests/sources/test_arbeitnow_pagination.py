"""Pagination validation, continuation token handling, and terminal detection tests (SOURCE-03-S03)."""

from __future__ import annotations

import pytest

from job_automation.contracts.adapter_results import Continuation
from job_automation.contracts.errors import ErrorCategory
from job_automation.sources.adapters.arbeitnow import ADAPTER_NAME, CONTINUATION_KIND, build_page_url
from tests.sources.arbeitnow_helpers import (
    FakeTransport,
    build_adapter,
    build_arbeitnow_config,
    load_fixture,
)


def test_first_page_produces_continuation_out_to_page_2() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is None
    assert not page.exhausted
    assert page.continuation_out is not None
    assert page.continuation_out.kind == CONTINUATION_KIND
    assert page.continuation_out.value == "2"
    assert page.continuation_out.adapter_name == ADAPTER_NAME


def test_resuming_with_continuation_fetches_next_page() -> None:
    page_2_bytes = load_fixture("page_2.json")
    transport = FakeTransport()
    transport.add(build_page_url(2), 200, {}, page_2_bytes)
    adapter, _ = build_adapter(transport=transport)

    continuation_in = Continuation(
        kind=CONTINUATION_KIND,
        value="2",
        source_key="arbeitnow_de",
        scope_id="scope-v1:arbeitnow-default-filtered",
        adapter_name=ADAPTER_NAME,
    )

    page = adapter.fetch_page(build_arbeitnow_config(), continuation=continuation_in)

    assert page.page_error is None
    assert build_page_url(2) in transport.calls
    assert page.continuation_in == continuation_in
    assert page.continuation_out is not None
    assert page.continuation_out.value == "3"
    assert not page.exhausted
    assert page.record_count == 1


def test_terminal_page_with_null_next_marks_exhausted() -> None:
    page_term_bytes = load_fixture("page_terminal.json")
    transport = FakeTransport()
    transport.add(build_page_url(3), 200, {}, page_term_bytes)
    adapter, _ = build_adapter(transport=transport)

    continuation_in = Continuation(
        kind=CONTINUATION_KIND,
        value="3",
        source_key="arbeitnow_de",
        scope_id="scope-v1:arbeitnow-default-filtered",
        adapter_name=ADAPTER_NAME,
    )

    page = adapter.fetch_page(build_arbeitnow_config(), continuation=continuation_in)

    assert page.page_error is None
    assert page.exhausted
    assert page.continuation_out is None
    assert page.record_count == 1


def test_empty_terminal_page_marks_exhausted_with_zero_records() -> None:
    empty_term_bytes = load_fixture("empty_terminal.json")
    transport = FakeTransport()
    transport.add(build_page_url(99), 200, {}, empty_term_bytes)
    adapter, _ = build_adapter(transport=transport)

    continuation_in = Continuation(
        kind=CONTINUATION_KIND,
        value="99",
        source_key="arbeitnow_de",
        scope_id="scope-v1:arbeitnow-default-filtered",
        adapter_name=ADAPTER_NAME,
    )

    page = adapter.fetch_page(build_arbeitnow_config(), continuation=continuation_in)

    assert page.page_error is None
    assert page.exhausted
    assert page.continuation_out is None
    assert page.record_count == 0


def test_empty_page_with_next_link_is_nonterminal() -> None:
    empty_with_next_bytes = load_fixture("empty_with_next.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, empty_with_next_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is None
    assert not page.exhausted
    assert page.continuation_out is not None
    assert page.continuation_out.value == "2"
    assert page.record_count == 0


def test_backward_or_same_page_in_next_url_yields_page_error() -> None:
    backward_response = b"""{
        "data": [{"slug": "job-1", "company_name": "C", "title": "T", "description": "<p>D</p>", "url": "https://www.arbeitnow.com/view/job-1"}],
        "links": {"first": "https://www.arbeitnow.com/api/job-board-api?page=1", "next": "https://www.arbeitnow.com/api/job-board-api?page=1"},
        "meta": {"current_page": 2}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(2), 200, {}, backward_response)
    adapter, _ = build_adapter(transport=transport)

    continuation_in = Continuation(
        kind=CONTINUATION_KIND,
        value="2",
        source_key="arbeitnow_de",
        scope_id="scope-v1:arbeitnow-default-filtered",
        adapter_name=ADAPTER_NAME,
    )

    page = adapter.fetch_page(build_arbeitnow_config(), continuation=continuation_in)

    # Valid items preserved even if pagination metadata fails
    assert page.record_count == 1
    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "does not advance" in page.page_error.message
    assert not page.exhausted
    assert page.continuation_out is None


def test_cross_host_next_url_yields_page_error() -> None:
    cross_host_response = b"""{
        "data": [],
        "links": {"next": "https://evil.invalid/api/job-board-api?page=3"},
        "meta": {"current_page": 2}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(2), 200, {}, cross_host_response)
    adapter, _ = build_adapter(transport=transport)

    continuation_in = Continuation(
        kind=CONTINUATION_KIND,
        value="2",
        source_key="arbeitnow_de",
        scope_id="scope-v1:arbeitnow-default-filtered",
        adapter_name=ADAPTER_NAME,
    )

    page = adapter.fetch_page(build_arbeitnow_config(), continuation=continuation_in)

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "fails Arbeitnow allowlist" in page.page_error.message
    assert not page.exhausted


def test_missing_links_object_yields_page_error() -> None:
    no_links_response = b'{"data": [], "meta": {"current_page": 1}}'
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, no_links_response)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert page.page_error.field_path == "links"
    assert not page.exhausted


def test_next_url_without_page_query_param_yields_page_error() -> None:
    no_page_param_response = b"""{
        "data": [],
        "links": {"next": "https://www.arbeitnow.com/api/job-board-api"},
        "meta": {"current_page": 1}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, no_page_param_response)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "no page query parameter" in page.page_error.message


def test_unsupported_continuation_kind_returns_page_error() -> None:
    adapter, _ = build_adapter()
    bad_continuation = Continuation(
        kind="cursor",  # Not "page"
        value="opaque_cursor_value",
        source_key="arbeitnow_de",
        scope_id="scope-v1:arbeitnow-default-filtered",
        adapter_name=ADAPTER_NAME,
    )

    page = adapter.fetch_page(build_arbeitnow_config(), continuation=bad_continuation)

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "Unsupported continuation kind" in page.page_error.message


@pytest.mark.parametrize("invalid_val", ["abc", "-5", "0", ""])
def test_invalid_continuation_value_returns_page_error(invalid_val: str) -> None:
    adapter, _ = build_adapter()
    bad_continuation = Continuation(
        kind=CONTINUATION_KIND,
        value=invalid_val,
        source_key="arbeitnow_de",
        scope_id="scope-v1:arbeitnow-default-filtered",
        adapter_name=ADAPTER_NAME,
    )

    page = adapter.fetch_page(build_arbeitnow_config(), continuation=bad_continuation)

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "not a valid positive" in page.page_error.message


def test_continuation_token_encode_decode_roundtrip() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())
    assert page.continuation_out is not None

    encoded = page.continuation_out.encode()
    assert encoded.startswith("cont-v1:")

    decoded = Continuation.decode(encoded)
    assert decoded.kind == page.continuation_out.kind
    assert decoded.value == page.continuation_out.value
    assert decoded.source_key == page.continuation_out.source_key
    assert decoded.scope_id == page.continuation_out.scope_id
    assert decoded.adapter_name == page.continuation_out.adapter_name

