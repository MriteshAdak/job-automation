"""HTTP transport, status classification, redirect safety, and error handling tests (SOURCE-03-S02)."""

from __future__ import annotations

import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.sources.adapters.arbeitnow import MAX_BODY_BYTES, build_page_url
from job_automation.sources.adapters.raw import RawCaptureSink
from tests.sources.arbeitnow_helpers import (
    FakeTransport,
    build_adapter,
    build_arbeitnow_config,
    load_fixture,
)


class FailingSink(RawCaptureSink):
    """Sink that simulates disk/memory failure."""

    def capture(self, content_bytes: bytes, identifier_hint: str = "") -> tuple[str, str]:
        raise OSError("Disk full / permission denied")

    def get(self, raw_payload_ref: str) -> bytes | None:
        return None


def test_200_json_response_success() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    target_url = build_page_url(1)
    transport.add(target_url, 200, {"content-type": "application/json"}, page_1_bytes)

    adapter, sink = build_adapter(transport=transport)
    config = build_arbeitnow_config()
    page = adapter.fetch_page(config)

    assert page.page_error is None
    assert page.record_count == 2
    assert len(page.items) == 2
    assert not page.exhausted
    assert page.continuation_out is not None
    assert page.continuation_out.value == "2"
    assert len(page.raw_response_refs) == 1
    # Check parent capture exists in sink
    assert sink.get(page.raw_response_refs[0]) == page_1_bytes


def test_401_authentication_error() -> None:
    transport = FakeTransport()
    transport.add(build_page_url(1), 401, {}, b'{"error":"unauthorized"}')
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.AUTHENTICATION
    assert not page.page_error.recoverable
    assert not page.exhausted


def test_403_permission_error() -> None:
    transport = FakeTransport()
    transport.add(build_page_url(1), 403, {}, b'{"error":"forbidden"}')
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.PERMISSION
    assert not page.page_error.recoverable
    assert not page.exhausted


def test_429_rate_limit_with_retry_after() -> None:
    transport = FakeTransport()
    transport.add(
        build_page_url(1),
        429,
        {"retry-after": "120"},
        b'{"error":"too many requests"}',
    )
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.RATE_LIMIT
    assert page.page_error.recoverable
    assert page.page_error.details is not None
    assert page.page_error.details.get("retry_after") == "120"
    assert not page.exhausted


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_5xx_transient_service_error(status_code: int) -> None:
    transport = FakeTransport()
    transport.add(build_page_url(1), status_code, {}, b"Internal Error")
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.TRANSIENT_SERVICE
    assert page.page_error.recoverable
    assert not page.exhausted


def test_304_without_cache_treated_as_validation_error() -> None:
    transport = FakeTransport()
    transport.add(build_page_url(1), 304, {}, b"")
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert not page.exhausted


class TimeoutTransport:
    def get(self, url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
        raise TimeoutError("Socket timed out")


def test_timeout_classified_as_transient_network() -> None:
    adapter, _ = build_adapter(transport=TimeoutTransport())
    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.TRANSIENT_NETWORK
    assert page.page_error.recoverable


class ConnectionErrorTransport:
    def get(self, url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
        raise OSError("Connection refused")


def test_connection_error_classified_as_transient_network() -> None:
    adapter, _ = build_adapter(transport=ConnectionErrorTransport())
    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.TRANSIENT_NETWORK
    assert page.page_error.recoverable


def test_body_exceeding_capacity_limit_returns_capacity_error() -> None:
    large_body = b"x" * (MAX_BODY_BYTES + 10)
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, large_body)
    adapter, sink = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.CAPACITY
    # Even if over limit, parent bytes were captured before check
    assert len(page.raw_response_refs) == 1
    assert sink.get(page.raw_response_refs[0]) == large_body


def test_invalid_utf8_response_returns_validation_error() -> None:
    invalid_bytes = b"\xff\xfe\x00\x00invalid-utf8"
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, invalid_bytes)
    adapter, sink = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert len(page.raw_response_refs) == 1
    assert sink.get(page.raw_response_refs[0]) == invalid_bytes


def test_malformed_json_returns_validation_error() -> None:
    malformed_json = b"<html><head><title>Cloudflare Challenge</title></head><body>...</body></html>"
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {"content-type": "text/html"}, malformed_json)
    adapter, sink = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert len(page.raw_response_refs) == 1
    assert sink.get(page.raw_response_refs[0]) == malformed_json


def test_bad_envelope_missing_data_returns_validation_error() -> None:
    bad_env_bytes = load_fixture("bad_envelope.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, bad_env_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert page.page_error.field_path == "data"


def test_redirect_to_allowed_host_followed() -> None:
    target_page_1 = load_fixture("page_1.json")
    transport = FakeTransport()
    initial_url = build_page_url(1)  # www.arbeitnow.com/api/job-board-api?page=1
    redirect_target = "https://arbeitnow.com/api/job-board-api?page=1"

    transport.add(initial_url, 301, {"location": redirect_target}, b"")
    transport.add(redirect_target, 200, {}, target_page_1)

    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is None
    assert page.record_count == 2
    assert len(transport.calls) == 2


def test_redirect_to_disallowed_host_rejected() -> None:
    transport = FakeTransport()
    initial_url = build_page_url(1)
    forbidden_target = "https://attacker.invalid/api/job-board-api?page=1"

    transport.add(initial_url, 302, {"location": forbidden_target}, b"")
    transport.add(forbidden_target, 200, {}, b"{}")

    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "fails Arbeitnow URL allowlist" in page.page_error.message
    # Forbidden target was never requested
    assert forbidden_target not in transport.calls


def test_redirect_loop_exceeding_max_hops_rejected() -> None:
    transport = FakeTransport()
    url_a = "https://www.arbeitnow.com/api/job-board-api?page=1"
    url_b = "https://arbeitnow.com/api/job-board-api?page=1"

    transport.add(url_a, 302, {"location": url_b}, b"")
    transport.add(url_b, 302, {"location": url_a}, b"")

    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "Too many redirects" in page.page_error.message or "Redirect" in page.page_error.message


def test_sink_capture_failure_classified_as_capacity_error() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    failing_sink = FailingSink()

    adapter, _ = build_adapter(transport=transport, sink=failing_sink)
    page = adapter.fetch_page(build_arbeitnow_config())

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.CAPACITY
    assert page.record_count == 0

