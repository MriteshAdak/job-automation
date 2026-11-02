"""Tests for retry classification, backoff calculation, and Retry-After parsing (INGEST-01-S04)."""

from datetime import datetime, timezone

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.ingestion.retry import (
    compute_backoff_delay,
    extract_retry_after,
    is_recoverable_error,
)


def test_is_recoverable_error_classification():
    # Recoverable
    rate_err = ClassifiedError.from_category(ErrorCategory.RATE_LIMIT, "429")
    net_err = ClassifiedError.from_category(ErrorCategory.TRANSIENT_NETWORK, "timeout")
    svc_err = ClassifiedError.from_category(ErrorCategory.TRANSIENT_SERVICE, "503")
    assert is_recoverable_error(rate_err) is True
    assert is_recoverable_error(net_err) is True
    assert is_recoverable_error(svc_err) is True

    # Terminal / Non-recoverable
    val_err = ClassifiedError.from_category(ErrorCategory.VALIDATION, "invalid schema")
    auth_err = ClassifiedError.from_category(ErrorCategory.AUTHENTICATION, "401")
    perm_err = ClassifiedError.from_category(ErrorCategory.PERMISSION, "403")
    cap_err = ClassifiedError.from_category(ErrorCategory.CAPACITY, "disk full")
    assert is_recoverable_error(val_err) is False
    assert is_recoverable_error(auth_err) is False
    assert is_recoverable_error(perm_err) is False
    assert is_recoverable_error(cap_err) is False
    assert is_recoverable_error(None) is False


def test_compute_backoff_delay():
    # attempt 1: factor * 2^0 = 1.0 * 1 = 1.0
    assert compute_backoff_delay(1, backoff_factor=1.0, backoff_max_seconds=30.0) == 1.0

    # attempt 2: factor * 2^1 = 1.0 * 2 = 2.0
    assert compute_backoff_delay(2, backoff_factor=1.0, backoff_max_seconds=30.0) == 2.0

    # attempt 3: factor * 2^2 = 1.0 * 4 = 4.0
    assert compute_backoff_delay(3, backoff_factor=1.0, backoff_max_seconds=30.0) == 4.0

    # attempt 10 exceeds max 30.0 -> clamped to 30.0
    assert compute_backoff_delay(10, backoff_factor=1.0, backoff_max_seconds=30.0) == 30.0

    # Retry-after overrides local backoff if larger
    assert compute_backoff_delay(1, 1.0, 30.0, retry_after_seconds=15.0) == 15.0

    # If local backoff is larger, local backoff wins
    assert compute_backoff_delay(5, 1.0, 30.0, retry_after_seconds=5.0) == 16.0


def test_extract_retry_after_numeric():
    err1 = ClassifiedError.from_category(
        category=ErrorCategory.RATE_LIMIT,
        message="Too many requests",
        details={"retry_after": 45.0},
    )
    assert extract_retry_after(err1) == 45.0

    err2 = ClassifiedError.from_category(
        category=ErrorCategory.RATE_LIMIT,
        message="Too many requests",
        details={"Retry-After": "60"},
    )
    assert extract_retry_after(err2) == 60.0


def test_extract_retry_after_http_date():
    now = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)
    # 30 seconds into the future
    err = ClassifiedError.from_category(
        category=ErrorCategory.RATE_LIMIT,
        message="Wait",
        details={"Retry-After": "Wed, 28 Oct 2026 10:00:30 GMT"},
    )
    delay = extract_retry_after(err, now_utc=now)
    assert delay == 30.0


def test_extract_retry_after_malformed_returns_none():
    err = ClassifiedError.from_category(
        category=ErrorCategory.RATE_LIMIT,
        message="Wait",
        details={"Retry-After": "not-a-valid-date-or-number"},
    )
    assert extract_retry_after(err) is None
