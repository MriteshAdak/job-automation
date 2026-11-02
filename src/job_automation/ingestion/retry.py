"""Retry policy, backoff calculation, and recoverable error classification (INGEST-01-S04).

Determines whether an attempt failure is transient and eligible for bounded retry,
parses safe Retry-After hints, and computes exponential backoff delays.
"""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory

_RECOVERABLE_CATEGORIES: frozenset[ErrorCategory] = frozenset({
    ErrorCategory.RATE_LIMIT,
    ErrorCategory.TRANSIENT_NETWORK,
    ErrorCategory.TRANSIENT_SERVICE,
})


def is_recoverable_error(error: ClassifiedError | None) -> bool:
    """Return True if the error is considered transient and safe to retry."""
    if error is None:
        return False
    # Capacity error requires halting acquisition rather than retry loops
    if error.category == ErrorCategory.CAPACITY:
        return False
    return error.category in _RECOVERABLE_CATEGORIES


def compute_backoff_delay(
    attempt: int,
    backoff_factor: float,
    backoff_max_seconds: float,
    retry_after_seconds: float | None = None,
) -> float:
    """Calculate delay before next retry attempt.

    Formula:
        local_delay = min(backoff_max, backoff_factor * 2 ** (attempt - 1))
        effective_delay = max(local_delay, retry_after) if retry_after else local_delay
    """
    if attempt < 1:
        attempt = 1

    local_delay = min(backoff_max_seconds, backoff_factor * (2 ** (attempt - 1)))

    if retry_after_seconds is not None and retry_after_seconds > 0.0:
        return max(local_delay, retry_after_seconds)

    return local_delay


def extract_retry_after(error: ClassifiedError | None, now_utc: datetime | None = None) -> float | None:
    """Extract Retry-After in seconds from error details if present."""
    if not error or not error.details:
        return None

    raw_val = error.details.get("retry_after")
    if raw_val is None:
        raw_val = error.details.get("Retry-After")
    if raw_val is None:
        return None

    # Check numeric seconds
    if isinstance(raw_val, (int, float)):
        return max(0.0, float(raw_val))

    if isinstance(raw_val, str):
        raw_str = raw_val.strip()
        try:
            return max(0.0, float(raw_str))
        except ValueError:
            pass

        # Try parsing HTTP date
        try:
            parsed_tuple = email.utils.parsedate_to_datetime(raw_str)
            if parsed_tuple:
                now = now_utc or datetime.now(timezone.utc)
                delta = (parsed_tuple - now).total_seconds()
                return max(0.0, delta)
        except Exception:
            pass

    return None

