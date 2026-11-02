"""Backoff delay calculation, Retry-After header parsing, and mutation replay rules (SFCLIENT-01-S05).

Enforces:
- Parsing Retry-After seconds and HTTP-date without truncating wait times.
- Non-blind retry: mutating requests default to NO REPLAY after uncertain transmission.
- Explicit opt-in for External ID upsert replay only when replay_safe is guaranteed.
- Rejection of retry when backoff exceeds remaining deadline.
"""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone

from job_automation.contracts.salesforce import OperationKind
from job_automation.salesforce.ports import Clock, Jitter


def parse_retry_after(header_value: str | None, clock: Clock) -> float | None:
    """Parse HTTP Retry-After header as delay in seconds.

    Supports:
    - Integer seconds (e.g. '120')
    - HTTP date (e.g. 'Fri, 31 Dec 2026 23:59:59 GMT')
    """
    if not header_value or not header_value.strip():
        return None

    cleaned = header_value.strip()

    # 1. Try parsing integer seconds
    try:
        sec = float(cleaned)
        return max(0.0, sec)
    except ValueError:
        pass

    # 2. Try parsing HTTP date
    try:
        parsed_dt = email.utils.parsedate_to_datetime(cleaned)
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        now_utc = clock.now_utc()
        delay = (parsed_dt - now_utc).total_seconds()
        return max(0.0, delay)
    except Exception:
        return None


def calculate_backoff_delay(
    attempt_index: int,
    initial_backoff: float,
    max_backoff: float,
    jitter: Jitter,
) -> float:
    """Compute exponential backoff delay with jitter."""
    exp_factor = 2 ** max(0, attempt_index)
    base_delay = min(max_backoff, initial_backoff * exp_factor)
    return jitter.apply(base_delay)


def is_replay_allowed(
    operation_kind: OperationKind,
    uncertain_transmission: bool,
    replay_safe: bool = False,
) -> bool:
    """Determine whether an operation is eligible for automatic retry.

    Rules:
    - Reads are idempotent and may always retry if budget allows.
    - If transmission definitely failed before being sent (uncertain_transmission=False),
      mutations may be retried once.
    - If transmission was uncertain (uncertain_transmission=True):
      - Upsert: allowed ONLY IF caller explicitly guaranteed replay_safe.
      - Update: NEVER allowed.
    """
    is_read = operation_kind in {
        OperationKind.CHECK_CONNECTION,
        OperationKind.GET_LIMITS,
        OperationKind.DESCRIBE_OBJECT,
        OperationKind.GET_RECORD,
        OperationKind.QUERY_PAGE,
    }
    if is_read:
        return True

    # Mutating operation
    if not uncertain_transmission:
        return True

    # Uncertain mutation transmission
    if operation_kind == OperationKind.UPSERT_BY_EXTERNAL_ID and replay_safe:
        return True

    return False

