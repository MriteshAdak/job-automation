"""Dependency-inversion ports and protocols for Salesforce gateway (SFCLIENT-01).

Isolates:
- HTTP transport execution and uncertain transmission reporting
- Credential storage and protected Windows references
- Token acquisition, session caching, and rotation lifecycle
- Monotonic timing, backoff sleeps, and jitter
- Safe diagnostic audit recording
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime


@runtime_checkable
class Clock(Protocol):
    """Monotonic and wall-clock provider interface."""

    def monotonic(self) -> float:
        """Return current monotonic time in seconds."""
        ...

    def now_utc(self) -> datetime:
        """Return current UTC wall-clock datetime."""
        ...


class DefaultClock:
    """Standard system clock."""

    def monotonic(self) -> float:
        return time.monotonic()

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


@runtime_checkable
class Sleeper(Protocol):
    """Sleep interface for backoff delays."""

    def sleep(self, seconds: float) -> None:
        """Block execution for specified duration in seconds."""
        ...


class DefaultSleeper:
    """Standard system sleeper."""

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@runtime_checkable
class Jitter(Protocol):
    """Jitter calculation interface for exponential backoff."""

    def apply(self, delay: float) -> float:
        """Apply random jitter to a computed backoff delay."""
        ...


class DefaultJitter:
    """Default jitter applying ±15% uniform variation, bounded strictly above 0."""

    def apply(self, delay: float) -> float:
        if delay <= 0:
            return 0.0
        variation = delay * 0.15
        return max(0.01, delay + random.uniform(-variation, variation))


class NoJitter:
    """Deterministic zero-jitter implementation for repeatable tests."""

    def apply(self, delay: float) -> float:
        return max(0.0, delay)


class HttpResponse(ContractModel):
    """Raw HTTP response record returned by HttpTransport."""

    status_code: int = Field(ge=100, le=599, description="HTTP response status code")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Response headers with normalized lowercase keys"
    )
    body: bytes = Field(default=b"", description="Raw response payload bytes")
    uncertain_transmission: bool = Field(
        default=False,
        description="True if request may have reached Salesforce before transport failure/timeout",
    )


@runtime_checkable
class HttpTransport(Protocol):
    """Outbound HTTPS transport port."""

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Execute a single HTTP request without hidden retries.

        May raise TransportError with uncertain_transmission metadata.
        """
        ...


class SalesforceSession(ContractModel):
    """In-memory authenticated session for Salesforce API calls."""

    access_token: str = Field(min_length=1, description="Opaque OAuth access token")
    instance_url: str = Field(min_length=1, description="Resolved Salesforce instance origin")
    token_type: str = Field(default="Bearer", description="OAuth token type")
    issued_at: float = Field(ge=0.0, description="Monotonic timestamp when session was acquired")
    expires_at: float | None = Field(
        default=None, description="Monotonic timestamp when session expires if known"
    )
    refresh_token: str | None = Field(
        default=None, description="Opaque refresh token if updated/rotated"
    )


@runtime_checkable
class CredentialStore(Protocol):
    """Secure credential storage interface."""

    def get_credential(self, ref: str) -> str | None:
        """Retrieve protected secret string by reference name or path."""
        ...

    def set_credential(self, ref: str, value: str) -> None:
        """Atomically persist protected secret string under reference name or path."""
        ...

    def delete_credential(self, ref: str) -> None:
        """Remove credential entry if present."""
        ...


@runtime_checkable
class TokenProvider(Protocol):
    """OAuth token acquisition, renewal, and rotation provider."""

    def get_session(
        self,
        force_refresh: bool = False,
    ) -> tuple[SalesforceSession | None, ClassifiedError | None]:
        """Return valid cached or freshly acquired session, or a classified error."""
        ...


class DiagnosticEvent(ContractModel):
    """Allowlisted diagnostic audit event containing zero secrets or payload data."""

    call_id: str = Field(description="UUID of the logical gateway operation")
    operation_kind: str = Field(description="Kind of operation executed")
    api_version: str = Field(description="Configured API version")
    attempt_number: int = Field(ge=1, description="Sequence number of HTTP attempt")
    purpose: str = Field(description="Attempt purpose (e.g. token_acquisition, resource_request)")
    http_status: int | None = Field(default=None, description="HTTP status code if received")
    safe_code: str | None = Field(default=None, description="Allowlisted safe code")
    duration_ms: float = Field(ge=0.0, description="Attempt duration in milliseconds")
    remote_outcome: str = Field(description="Remote mutation outcome")
    recovery_action: str = Field(description="Recovery action hint")
    utc_timestamp: UtcDatetime = Field(description="UTC timestamp of the event")
    quota_remaining: int | None = Field(
        default=None, ge=0, description="Safe observed quota allowance if available"
    )


@runtime_checkable
class SafeDiagnosticsRecorder(Protocol):
    """Receiver of allowlisted diagnostic audit events."""

    def record_event(self, event: DiagnosticEvent) -> None:
        """Record an allowlisted diagnostic event without throwing or re-executing mutations."""
        ...


class NoOpDiagnosticsRecorder:
    """Null diagnostic recorder."""

    def record_event(self, event: DiagnosticEvent) -> None:
        pass

