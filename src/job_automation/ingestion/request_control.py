"""Request limits, budgets, timeouts, and domain rate limiting (INGEST-01-S04).

Enforces monotonic deadlines, request and page budgets, and inter-request
spacing shared across source aliases under the same provider/domain.
"""

from __future__ import annotations

from typing import Any

from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.ports import ClockProtocol, SleeperProtocol
from job_automation.sources.models import EffectiveSource


class RequestBudget:
    """Tracks and bounds physical outbound requests, logical pages, and deadlines."""

    def __init__(
        self,
        max_requests: int,
        max_pages: int,
        max_response_bytes: int,
        timeout_seconds: float,
        source_deadline_seconds: float,
        start_monotonic: float,
    ) -> None:
        self.max_requests = max_requests
        self.remaining_requests = max_requests
        self.max_pages = max_pages
        self.remaining_pages = max_pages
        self.max_response_bytes = max_response_bytes
        self.timeout_seconds = timeout_seconds
        self.start_monotonic = start_monotonic
        self.deadline_monotonic = start_monotonic + source_deadline_seconds

    @classmethod
    def from_source_and_options(
        cls,
        effective_source: EffectiveSource,
        options: ControllerOptions,
        start_monotonic: float,
    ) -> RequestBudget:
        """Construct budget taking the stricter cap between source and controller."""
        eff_policy = effective_source.request_policy

        # Page cap: minimum of source config (if defined) and controller options
        max_pages = options.max_pages
        if eff_policy and eff_policy.max_pages is not None:
            max_pages = min(max_pages, eff_policy.max_pages)

        # Timeout: minimum of source config (if defined) and controller options
        timeout = options.timeout_seconds
        if eff_policy and eff_policy.timeout_seconds is not None:
            timeout = min(timeout, eff_policy.timeout_seconds)

        return cls(
            max_requests=options.max_requests,
            max_pages=max_pages,
            max_response_bytes=options.max_response_bytes,
            timeout_seconds=timeout,
            source_deadline_seconds=options.source_deadline_seconds,
            start_monotonic=start_monotonic,
        )

    def has_requests(self) -> bool:
        return self.remaining_requests > 0

    def has_pages(self) -> bool:
        return self.remaining_pages > 0

    def consume_request(self) -> None:
        if self.remaining_requests > 0:
            self.remaining_requests -= 1

    def consume_page(self) -> None:
        if self.remaining_pages > 0:
            self.remaining_pages -= 1

    def is_deadline_exceeded(self, current_monotonic: float) -> bool:
        return current_monotonic >= self.deadline_monotonic

    def remaining_deadline(self, current_monotonic: float) -> float:
        return max(0.0, self.deadline_monotonic - current_monotonic)

    def effective_timeout(self, current_monotonic: float) -> float:
        """Effective timeout for the next request bounded by remaining deadline."""
        rem = self.remaining_deadline(current_monotonic)
        return min(self.timeout_seconds, max(0.1, rem))


class DomainRateLimiter:
    """Enforces inter-request spacing per domain/provider key."""

    def __init__(self) -> None:
        self._last_request_times: dict[str, float] = {}

    def enforce_spacing(
        self,
        domain_key: str,
        spacing_seconds: float,
        clock: ClockProtocol,
        sleeper: SleeperProtocol,
    ) -> float:
        """Sleep if needed to respect spacing since the last request to this domain.

        Returns the delay slept in seconds.
        """
        if spacing_seconds <= 0.0:
            return 0.0

        now = clock.monotonic()
        last_time = self._last_request_times.get(domain_key)
        delay_slept = 0.0

        if last_time is not None:
            elapsed = now - last_time
            needed = spacing_seconds - elapsed
            if needed > 0.0:
                sleeper.sleep(needed)
                delay_slept = needed

        self._last_request_times[domain_key] = clock.monotonic()
        return delay_slept
