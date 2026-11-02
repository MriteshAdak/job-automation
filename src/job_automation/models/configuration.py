"""Configuration models and URL validation for local model execution (LLM-01-S02).

Enforces:
- Loopback-only service URL without user credentials, query strings, or fragments.
- Finite positive timeouts, retry limits, and size ceilings.
- Typed capabilities per local model.
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from pydantic import Field, field_validator

from job_automation.contracts.base import ContractModel

LOOPBACK_HOSTNAMES: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_loopback_url(v: str) -> str:
    """Validate that a URL strictly targets a local loopback interface.

    Rejects credentials, query parameters, fragment identifiers, non-loopback hosts,
    and remote redirection targets.
    """
    if not isinstance(v, str) or not v.strip():
        raise ValueError("Model service URL must be a non-empty string")

    raw_val = v.strip()
    # Normalize IPv6 loopback without brackets if passed
    if "://::1" in raw_val and "://[::1]" not in raw_val:
        raw_val = raw_val.replace("://::1", "://[::1]")

    parsed = urlparse(raw_val)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Model service URL scheme must be http or https, got '{parsed.scheme}'")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Model service URL must not contain userinfo or credentials")

    if parsed.query:
        raise ValueError("Model service URL must not contain query parameters")

    if parsed.fragment:
        raise ValueError("Model service URL must not contain fragment identifier")

    raw_hostname = (parsed.hostname or "").lower()
    if not raw_hostname:
        raise ValueError("Model service URL must include a hostname")

    if raw_hostname not in LOOPBACK_HOSTNAMES:
        raise ValueError(
            f"Model service URL must point to loopback address (127.0.0.1, localhost, or ::1), got '{raw_hostname}'"
        )

    try:
        port = parsed.port
    except ValueError as err:
        raise ValueError(f"Model service URL port must be between 1 and 65535: {err}") from err

    if port is not None and not (1 <= port <= 65535):
        raise ValueError(f"Model service URL port must be between 1 and 65535, got {port}")

    if parsed.path and parsed.path not in {"", "/"}:
        if ".." in parsed.path:
            raise ValueError("Model service URL path must not contain directory traversal")

    return v.strip()


def verify_resolved_loopback(hostname: str) -> None:
    """Verify that resolving the hostname yields exclusively loopback addresses."""
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname '{hostname}': {exc}") from exc

    for entry in addrinfo:
        ip = entry[4][0]
        if ip not in {"127.0.0.1", "::1"} and not ip.startswith("127."):
            raise ValueError(
                f"Hostname '{hostname}' resolved to non-loopback address '{ip}'"
            )


class ModelCapabilities(ContractModel):
    """Declared or discovered capabilities for a specific model."""

    model_identifier: str = Field(min_length=1, description="Model identifier/tag")
    max_context_tokens: int = Field(gt=0, description="Maximum context window capacity in tokens")
    default_output_reserve: int = Field(
        default=512, ge=0, description="Tokens reserved for model completion output"
    )
    dimension: int | None = Field(
        default=None, gt=0, description="Vector dimension if embedding model"
    )
    expected_digest: str | None = Field(
        default=None, description="Expected SHA256 digest of model weights if pinned"
    )


class ModelProviderSettings(ContractModel):
    """Local model provider execution, deadline, and retry configuration."""

    service_url: str | None = Field(
        default=None,
        description="Optional local service URL; overrides AppConfig.model_service_url if provided",
    )
    connect_timeout_seconds: float = Field(
        default=5.0, gt=0.0, description="Maximum seconds to establish TCP connection"
    )
    read_timeout_seconds: float = Field(
        default=60.0, gt=0.0, description="Maximum seconds waiting for response bytes"
    )
    total_deadline_seconds: float = Field(
        default=120.0, gt=0.0, description="Total deadline across queue wait and all attempts"
    )
    max_transport_attempts: int = Field(
        default=3, ge=1, le=10, description="Total physical transport attempts allowed"
    )
    max_malformed_regenerations: int = Field(
        default=0, ge=0, le=1, description="Maximum regenerations allowed on malformed output (max 1)"
    )
    initial_backoff_seconds: float = Field(
        default=0.5, ge=0.0, description="Initial retry backoff delay"
    )
    backoff_factor: float = Field(
        default=2.0, ge=1.0, description="Multiplicative factor for exponential backoff"
    )
    max_backoff_seconds: float = Field(
        default=5.0, ge=0.0, description="Maximum retry backoff delay ceiling"
    )
    max_response_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, description="Maximum allowed response payload size (10MB)"
    )
    max_batch_size: int = Field(
        default=64, ge=1, description="Maximum texts in a single embedding batch call"
    )
    default_context_ceiling: int = Field(
        default=8192, gt=0, description="Default context window ceiling if unconfigured for model"
    )
    reserved_output_tokens: int = Field(
        default=512, ge=0, description="Default completion token reserve for generation"
    )
    safety_margin_tokens: int = Field(
        default=64, ge=0, description="Safety allowance buffer for tokenization estimation"
    )
    models: dict[str, ModelCapabilities] = Field(
        default_factory=dict,
        description="Known model capability profiles keyed by model identifier",
    )

    @field_validator("service_url")
    @classmethod
    def _validate_service_url(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_loopback_url(v)
        return None
