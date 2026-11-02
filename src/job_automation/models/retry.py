"""Retry and deadline control for local model execution (LLM-01-S06).

Enforces:
- Single unified transport-attempt cap across service retries and malformed output regenerations.
- Strict bounded total call deadline.
- Exponential backoff bounded by remaining deadline.
- At most 1 optional malformed output regeneration attempt.
"""

from __future__ import annotations

from job_automation.contracts.errors import ClassifiedError
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.ports import Clock, Sleeper


class RetryController:
    """Controls attempt counts, backoff delays, and deadline tracking for a call."""

    def __init__(
        self,
        settings: ModelProviderSettings,
        clock: Clock,
        sleeper: Sleeper,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.sleeper = sleeper
        self.start_monotonic = self.clock.monotonic()
        self.total_attempts: int = 0
        self.malformed_regenerations: int = 0

    def remaining_deadline(self) -> float:
        """Seconds remaining before overall logical call deadline is reached."""
        elapsed = self.clock.monotonic() - self.start_monotonic
        return max(0.0, self.settings.total_deadline_seconds - elapsed)

    def is_deadline_exceeded(self) -> bool:
        """Check if overall call deadline has elapsed."""
        return self.remaining_deadline() <= 0.0

    def can_attempt(self) -> bool:
        """Check if another physical transport attempt is permitted."""
        return (
            self.total_attempts < self.settings.max_transport_attempts
            and not self.is_deadline_exceeded()
        )

    def should_retry_error(self, error: ClassifiedError) -> bool:
        """Check if classified error is eligible for service retry within budget."""
        if not error.recoverable:
            return False
        return self.can_attempt()

    def should_regenerate_malformed(self) -> bool:
        """Check if malformed output is eligible for internal regeneration within budget."""
        if self.malformed_regenerations >= self.settings.max_malformed_regenerations:
            return False
        return self.can_attempt()

    def record_attempt(self, purpose: str) -> int:
        """Record the start of a physical attempt. Returns 1-based attempt number."""
        self.total_attempts += 1
        if purpose == "regeneration_malformed_output":
            self.malformed_regenerations += 1
        return self.total_attempts

    def execute_backoff(self, attempt_number: int, retry_after_header: str | None = None) -> bool:
        """Sleep for exponential backoff or retry-after, bounded by remaining deadline.

        Returns True if backoff succeeded, False if deadline was exhausted.
        """
        remaining = self.remaining_deadline()
        if remaining <= 0.0:
            return False

        delay = self.settings.initial_backoff_seconds * (
            self.settings.backoff_factor ** max(0, attempt_number - 1)
        )
        delay = min(delay, self.settings.max_backoff_seconds)

        if retry_after_header:
            try:
                header_delay = float(retry_after_header)
                if header_delay > 0:
                    delay = max(delay, header_delay)
            except ValueError:
                pass

        if delay > remaining:
            # Cannot complete required backoff before deadline
            self.sleeper.sleep(remaining)
            return False

        self.sleeper.sleep(delay)
        return not self.is_deadline_exceeded()

