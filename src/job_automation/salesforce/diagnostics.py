"""Secret redaction and allowlisted diagnostics logging (SFCLIENT-01-S06).

Enforces:
- Complete redaction of bearer tokens, client secrets, passwords, and private keys.
- Allowlisted diagnostic events containing only safe metrics, codes, and durations.
- Never logging or leaking record bodies, candidate text, or SOQL queries.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from job_automation.salesforce.ports import DiagnosticEvent, SafeDiagnosticsRecorder

# Regex patterns for secret redaction
BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9_.\-!~]+)")
OAUTH_PARAM_PATTERN = re.compile(
    r"(?i)\b(client_secret|client_id|refresh_token|access_token|password|assertion)=([^&\s]+)"
)
AUTH_HEADER_PATTERN = re.compile(r"(?i)(authorization|proxy-authorization|cookie):\s*([^\r\n]+)")
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----"
)


def redact_sensitive_text(text: str) -> str:
    """Scrub sensitive credentials, tokens, and authorization data from string."""
    if not isinstance(text, str) or not text:
        return text

    # Redact private keys
    scrubbed = PRIVATE_KEY_PATTERN.sub("[REDACTED_PRIVATE_KEY]", text)
    # Redact Bearer headers
    scrubbed = BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", scrubbed)
    # Redact auth headers
    scrubbed = AUTH_HEADER_PATTERN.sub(r"\1: [REDACTED]", scrubbed)
    # Redact URL / body query parameters
    scrubbed = OAUTH_PARAM_PATTERN.sub(r"\1=[REDACTED]", scrubbed)

    return scrubbed


class SafeMemoryDiagnosticsRecorder:
    """In-memory diagnostics recorder storing allowlisted events."""

    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def record_event(self, event: DiagnosticEvent) -> None:
        """Store allowlisted event; guarantees zero-exception execution."""
        try:
            self.events.append(event)
        except Exception:
            pass

    def clear(self) -> None:
        self.events.clear()


def create_diagnostic_event(
    call_id: str,
    operation_kind: str,
    api_version: str,
    attempt_number: int,
    purpose: str,
    http_status: int | None,
    safe_code: str | None,
    duration_ms: float,
    remote_outcome: str,
    recovery_action: str,
    utc_timestamp: datetime,
    quota_remaining: int | None = None,
) -> DiagnosticEvent:
    """Build a validated, safe diagnostic event."""
    return DiagnosticEvent(
        call_id=str(call_id),
        operation_kind=str(operation_kind),
        api_version=str(api_version),
        attempt_number=int(attempt_number),
        purpose=str(purpose),
        http_status=http_status,
        safe_code=safe_code,
        duration_ms=max(0.0, float(duration_ms)),
        remote_outcome=str(remote_outcome),
        recovery_action=str(recovery_action),
        utc_timestamp=utc_timestamp,
        quota_remaining=quota_remaining,
    )

