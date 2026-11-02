"""Scripted model transport and synthetic timing for LLM-01 testing.

Provides fully deterministic simulation of HTTP responses, socket errors,
timeouts, delays, and payload inspection without network traffic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class ScriptedClock:
    """Controllable monotonic and UTC clock for deterministic testing."""

    def __init__(self, initial_monotonic: float = 1000.0, initial_utc: datetime | None = None) -> None:
        self._mono = initial_monotonic
        self._utc = initial_utc or datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self._mono

    def now_utc(self) -> datetime:
        return self._utc

    def advance(self, seconds: float) -> None:
        self._mono += seconds


class ScriptedSleeper:
    """Sleeper that advances a ScriptedClock without real wall-clock delays."""

    def __init__(self, clock: ScriptedClock) -> None:
        self.clock = clock
        self.total_slept: float = 0.0
        self.sleep_calls: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.total_slept += seconds
        self.sleep_calls.append(seconds)
        self.clock.advance(seconds)


class ScriptedModelTransport:
    """Scripted HTTP transport for fake local model execution."""

    def __init__(self, clock: ScriptedClock | None = None) -> None:
        self.clock = clock
        self._queued_responses: list[tuple[str, int, dict[str, str], bytes, float]] = []
        self._queued_exceptions: list[tuple[str, Exception]] = []
        self.recorded_calls: list[dict[str, Any]] = []

    def queue_response(
        self,
        path: str,
        status: int,
        headers: dict[str, str] | None = None,
        body: bytes | dict[str, Any] | str = b"",
        delay_seconds: float = 0.0,
    ) -> None:
        """Queue a synthetic response for a specific path."""
        if isinstance(body, dict):
            body_bytes = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body

        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        if "content-type" not in hdrs:
            hdrs["content-type"] = "application/json"
        if "content-length" not in hdrs:
            hdrs["content-length"] = str(len(body_bytes))

        self._queued_responses.append((path, status, hdrs, body_bytes, delay_seconds))

    def queue_exception(self, path: str, exc: Exception) -> None:
        """Queue an exception to be raised on the next call for path."""
        self._queued_exceptions.append((path, exc))

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, str], bytes]:
        """Process a POST request against queued responses/exceptions."""
        self.recorded_calls.append({
            "path": path,
            "payload": payload,
            "timeout_seconds": timeout_seconds,
        })

        # Check for queued exceptions
        for idx, (target_path, exc) in enumerate(self._queued_exceptions):
            if target_path == path or target_path == "*":
                self._queued_exceptions.pop(idx)
                raise exc

        # Check for queued responses
        for idx, (target_path, status, headers, body_bytes, delay) in enumerate(self._queued_responses):
            if target_path == path or target_path == "*":
                self._queued_responses.pop(idx)
                if delay > 0 and self.clock:
                    self.clock.advance(delay)
                return status, headers, body_bytes

        # Default fallback: 404
        return 404, {"content-type": "application/json"}, b'{"error": "No scripted response queued"}'

