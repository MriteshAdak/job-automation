"""Safe diagnostics, log sanitization, and allowlisted projections (LLM-01-S07).

Prevents leaking private prompt content, raw generated output, vector embeddings,
or credentials into log streams or unredacted error strings.
"""

from __future__ import annotations

import re
from typing import Any

from job_automation.contracts.models import ModelResult


def redact_url_credentials(url: str) -> str:
    """Redact userinfo from a URL string."""
    return re.sub(r"://[^@]+@", "://[REDACTED]@", url)


def sanitize_log_text(text: str, max_length: int = 300) -> str:
    """Sanitize text for single-line log emission, removing control chars and newlines."""
    if not text:
        return ""
    # Replace newlines and carriage returns with space
    flattened = " ".join(text.split())
    # Remove control characters except standard space
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", flattened)
    if len(cleaned) > max_length:
        return cleaned[:max_length] + "..."
    return cleaned


def safe_result_summary(result: ModelResult) -> dict[str, Any]:
    """Produce an allowlisted diagnostic projection of a ModelResult."""
    summary: dict[str, Any] = {
        "call_id": str(result.call_id),
        "model_identifier": result.model_identifier,
        "latency_ms": result.latency_ms,
        "has_error": result.error is not None,
    }
    if result.model_digest:
        summary["model_digest"] = result.model_digest
    if result.error:
        summary["error_category"] = str(result.error.category)
        summary["error_message"] = sanitize_log_text(result.error.message)
    if result.token_usage:
        summary["token_usage"] = result.token_usage.model_dump()
    return summary

