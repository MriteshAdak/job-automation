"""Error classification and mapping for local model execution (LLM-01-S06).

Maps transport failures, HTTP status codes, and model runtime diagnostics
into standardized ClassifiedError instances with accurate recoverability flags.
"""

from __future__ import annotations

import json
import socket
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory


def classify_transport_error(exc: Exception) -> ClassifiedError:
    """Classify physical network/socket/timeout transport exceptions."""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_NETWORK,
            "Local model service read/connect timeout",
            details={"exception_type": type(exc).__name__},
        )

    if isinstance(exc, (ConnectionRefusedError, ConnectionResetError)):
        return ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_NETWORK,
            "Local model service connection refused or reset",
            details={"exception_type": type(exc).__name__},
        )

    if isinstance(exc, ValueError) and ("exceed" in str(exc).lower() and "maximum allowed" in str(exc).lower()):
        return ClassifiedError.from_category(
            ErrorCategory.MODEL_OUTPUT,
            "Local model response exceeded maximum allowed payload size",
            details={"reason": "response_size_exceeded"},
        )

    return ClassifiedError.from_category(
        ErrorCategory.TRANSIENT_NETWORK,
        f"Transport communication error with local model service: {type(exc).__name__}",
        details={"exception_type": type(exc).__name__},
    )


def classify_http_status(
    status: int,
    body_bytes: bytes,
    headers: dict[str, str] | None = None,
) -> ClassifiedError:
    """Map HTTP response code and response diagnostics to ClassifiedError."""
    body_text = ""
    error_msg = ""
    try:
        body_text = body_bytes.decode("utf-8", errors="replace")
        if body_text.startswith("{"):
            payload = json.loads(body_text)
            if isinstance(payload, dict):
                error_msg = str(payload.get("error", ""))
    except Exception:
        pass

    details: dict[str, Any] = {"http_status": status}
    if error_msg:
        details["runtime_error"] = error_msg

    if status == 400:
        lowered = (error_msg or body_text).lower()
        if any(term in lowered for term in ["context length", "token limit", "prompt is too long", "exceeds context"]):
            return ClassifiedError.from_category(
                ErrorCategory.CONTEXT_BUDGET,
                "Model runtime rejected request: context length exceeded",
                details=details,
            )
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            f"Model runtime rejected request parameters: {error_msg or 'Bad Request'}",
            details=details,
        )

    if status == 401:
        return ClassifiedError.from_category(
            ErrorCategory.AUTHENTICATION,
            "Authentication failed communicating with model service",
            details=details,
        )

    if status == 403:
        return ClassifiedError.from_category(
            ErrorCategory.PERMISSION,
            "Permission denied communicating with model service",
            details=details,
        )

    if status == 404:
        lowered = (error_msg or body_text).lower()
        if "model" in lowered and "not found" in lowered:
            return ClassifiedError.from_category(
                ErrorCategory.MISSING_CONFIGURATION,
                f"Configured model not found on local runtime: {error_msg}",
                details=details,
            )
        return ClassifiedError.from_category(
            ErrorCategory.MISSING_CONFIGURATION,
            f"Endpoint route not found on local model service (HTTP 404): {error_msg or 'Not Found'}",
            details=details,
        )

    if status == 429:
        retry_after = None
        if headers:
            retry_after = headers.get("retry-after")
        if retry_after:
            details["retry_after"] = retry_after
        return ClassifiedError.from_category(
            ErrorCategory.RATE_LIMIT,
            "Local model runtime rate limit encountered",
            details=details,
        )

    if status == 507 or "out of memory" in (error_msg or body_text).lower() or "vram" in (error_msg or body_text).lower():
        return ClassifiedError.from_category(
            ErrorCategory.CAPACITY,
            "Local model runtime memory/capacity exhausted (OOM / VRAM)",
            details=details,
        )

    if status in {502, 503, 504}:
        return ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_SERVICE,
            f"Local model service temporarily unavailable (HTTP {status})",
            details=details,
        )

    if 500 <= status < 600:
        return ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_SERVICE,
            f"Local model service internal server error (HTTP {status}): {error_msg or 'Internal Error'}",
            details=details,
        )

    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        f"Unexpected HTTP status {status} from local model service",
        details=details,
    )
