"""Conservative manual posting identity and URL validation (SOURCE-02-S03).

Provides:
- Explicit-ID preference with zero-padding and case preservation
- Conservative URL-based fallback identity
- Safe URL syntax validation preventing credentials and non-HTTP schemes
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse


def validate_http_url(url: str) -> tuple[bool, str | None]:
    """Validate that a URL is a syntactically valid HTTP(S) URL without credentials.

    Returns:
        (True, None) if valid.
        (False, error_code) if invalid ('missing_url', 'invalid_url_scheme',
        'url_has_credentials', 'missing_url_host', 'invalid_url_format').
    """
    if not url or not url.strip():
        return False, "missing_url"

    # Reject leading/trailing whitespace rather than silently mutating the input
    if url != url.strip():
        return False, "invalid_url_format"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid_url_format"

    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "invalid_url_scheme"

    if not parsed.netloc:
        return False, "missing_url_host"

    # Reject credentials/userinfo in URL (security rule)
    if parsed.username or parsed.password:
        return False, "url_has_credentials"

    return True, None


def derive_manual_posting_id(
    explicit_id: str | None,
    source_url: str,
) -> tuple[str, str]:
    """Derive the source_posting_id for a manual record.

    Prefers an explicit non-blank ID (preserving exact casing and leading zeros).
    Falls back to a deterministic, conservative SHA-256 digest of the exact source URL.

    Returns:
        tuple[source_posting_id, identity_method]
        where identity_method is 'explicit_id' or 'url_fallback_v1'.
    """
    if explicit_id is not None and explicit_id != "":
        # Preserve exact casing and leading zeros, but check it isn't purely whitespace
        if not explicit_id.strip():
            raise ValueError("Explicit posting ID cannot be purely whitespace")
        return explicit_id, "explicit_id"

    # Fallback to URL identity
    is_valid, err = validate_http_url(source_url)
    if not is_valid:
        raise ValueError(f"Cannot derive URL identity from invalid URL: {err}")

    # Conservative URL fallback: namespaced sha256 of exact URL
    url_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return f"url-v1:{url_hash}", "url_fallback_v1"

