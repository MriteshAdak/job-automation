"""SYNC-01 bounded retry calculations, delays, and error classifications (SYNC-01-S08).

Enforces:
- 3 maximum delivery attempts per outbox operation
- Exponential backoff with jitter: 5.0s base, 300.0s ceiling
- Respecting remote Retry-After / retry_not_before headers
- Distinguishing safely retryable transient errors from terminal failures requiring repair
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.salesforce import GatewayFailure, RemoteOutcome

DEFAULT_BASE_DELAY_SECONDS: float = 5.0
DEFAULT_MAX_DELAY_SECONDS: float = 300.0
DEFAULT_MAX_ATTEMPTS: int = 3
MAX_RECONCILIATION_READS: int = 6


def calculate_sync_backoff(
    attempt_count: int,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_MAX_DELAY_SECONDS,
    jitter_factor: float = 0.2,
) -> float:
    """Calculate exponential backoff delay with jitter."""
    # attempt_count is 1-indexed (after first failure)
    exponent = max(0, attempt_count - 1)
    raw = base_delay * (2.0 ** exponent)
    capped = min(raw, max_delay)

    # Apply symmetric jitter: capped +/- jitter_factor * capped
    jitter_range = capped * jitter_factor
    jittered = capped + random.uniform(-jitter_range, jitter_range)
    return max(0.5, min(jittered, max_delay))


def compute_next_attempt_at(
    attempt_count: int,
    failure: GatewayFailure | None = None,
    now: datetime | None = None,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_MAX_DELAY_SECONDS,
) -> UtcDatetime:
    """Compute the next attempt timestamp, honoring retry_not_before if later."""
    now_dt = now or datetime.now(timezone.utc)
    delay_sec = calculate_sync_backoff(attempt_count, base_delay=base_delay, max_delay=max_delay)
    calculated_time = now_dt + timedelta(seconds=delay_sec)

    if failure and failure.retry_not_before is not None:
        if failure.retry_not_before > calculated_time:
            return failure.retry_not_before

    return calculated_time


def is_safely_retryable(failure: GatewayFailure) -> bool:
    """Determine if a gateway failure can be safely retried without human repair or reconciliation."""
    # If the outcome is unknown, it cannot be blindly retried: it must enter reconciliation!
    if failure.remote_outcome == RemoteOutcome.UNKNOWN:
        return False

    cat = failure.error.category
    # Safe retryable categories
    if cat in (ErrorCategory.TRANSIENT_NETWORK, ErrorCategory.TRANSIENT_SERVICE, ErrorCategory.RATE_LIMIT):
        return True

    return False

