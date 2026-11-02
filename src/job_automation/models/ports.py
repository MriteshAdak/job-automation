"""Interface protocols (ports) for model execution components (LLM-01-S01).

Follows dependency-inversion principles so transport, timing, input resolution,
schema validation, and audit recording are mockable and isolated.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from job_automation.models.records import (
    BoundEmbeddingInput,
    BoundGenerationInput,
    LogicalCallAuditRecord,
)


@runtime_checkable
class Clock(Protocol):
    """Monotonic and wall clock interface."""

    def monotonic(self) -> float:
        """Return current monotonic time in seconds."""
        ...

    def now_utc(self) -> datetime:
        """Return current UTC wall-clock time."""
        ...


class DefaultClock:
    """Standard system clock implementation."""

    def monotonic(self) -> float:
        return time.monotonic()

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


@runtime_checkable
class Sleeper(Protocol):
    """Sleep interface for backoff delays."""

    def sleep(self, seconds: float) -> None:
        """Block execution for specified seconds."""
        ...


class DefaultSleeper:
    """Standard system sleeper."""

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@runtime_checkable
class InputResolver(Protocol):
    """Caller-provided resolver for bound input content."""

    def resolve_generation_input(self, call_id: uuid.UUID) -> BoundGenerationInput | None:
        """Resolve immutable generation prompt payload by call_id."""
        ...

    def resolve_embedding_input(self, call_id: uuid.UUID) -> BoundEmbeddingInput | None:
        """Resolve immutable embedding texts by call_id."""
        ...


@runtime_checkable
class AuditRecorder(Protocol):
    """Receiver of complete logical call audit records."""

    def record_call(self, record: LogicalCallAuditRecord) -> None:
        """Persist or record a completed logical call audit event."""
        ...


@runtime_checkable
class Tokenizer(Protocol):
    """Token counting interface for preflight context budget checks."""

    def count_tokens(self, text: str) -> int:
        """Count or conservatively estimate tokens for the given text."""
        ...


@runtime_checkable
class ModelTransport(Protocol):
    """Low-level transport for communicating with local model service."""

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, str], bytes]:
        """Execute a POST request to the local model runtime.

        Returns (status_code, headers_dict, response_body_bytes).
        """
        ...

