"""Monotonic deadline and send budget management (SFCLIENT-01-S05).

Enforces:
- Single unified budget across authentication, resource calls, and retries.
- Ceilings on total HTTP sends (6), resource sends (3), and token sends (2).
- Monotonic wall-clock deadline consumption across sleeps and I/O.
"""

from __future__ import annotations

from job_automation.salesforce.ports import Clock


class CallBudget:
    """Tracks and enforces logical operation deadlines and HTTP send counts."""

    def __init__(
        self,
        clock: Clock,
        total_timeout_seconds: float = 60.0,
        max_total_sends: int = 6,
        max_resource_sends: int = 3,
        max_token_sends: int = 2,
    ) -> None:
        self.clock = clock
        self.start_monotonic = clock.monotonic()
        self.deadline_monotonic = self.start_monotonic + max(1.0, total_timeout_seconds)

        self.max_total_sends = max(1, max_total_sends)
        self.max_resource_sends = max(1, max_resource_sends)
        self.max_token_sends = max(1, max_token_sends)

        self.total_sends: int = 0
        self.resource_sends: int = 0
        self.token_sends: int = 0

    def remaining_time(self) -> float:
        """Return remaining seconds before monotonic deadline."""
        now = self.clock.monotonic()
        return max(0.0, self.deadline_monotonic - now)

    def is_deadline_exceeded(self) -> bool:
        """True if monotonic deadline has expired."""
        return self.remaining_time() <= 0.0

    def can_send_token(self) -> bool:
        """True if token endpoint send is permitted by budget and deadline."""
        if self.is_deadline_exceeded():
            return False
        if self.total_sends >= self.max_total_sends:
            return False
        if self.token_sends >= self.max_token_sends:
            return False
        return True

    def can_send_resource(self) -> bool:
        """True if resource endpoint send is permitted by budget and deadline."""
        if self.is_deadline_exceeded():
            return False
        if self.total_sends >= self.max_total_sends:
            return False
        if self.resource_sends >= self.max_resource_sends:
            return False
        return True

    def record_token_send(self) -> None:
        """Increment token and total send counters."""
        self.total_sends += 1
        self.token_sends += 1

    def record_resource_send(self) -> None:
        """Increment resource and total send counters."""
        self.total_sends += 1
        self.resource_sends += 1

    def is_exhausted(self) -> bool:
        """True if budget prevents further network requests."""
        return (
            self.is_deadline_exceeded()
            or self.total_sends >= self.max_total_sends
            or (self.resource_sends >= self.max_resource_sends and self.token_sends >= self.max_token_sends)
        )

