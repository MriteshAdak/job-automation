"""Conservative URL validation, comparison, and job-specificity classification."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_GENERIC_CAREERS_PATHS = {
    "",
    "/",
    "/careers",
    "/careers/",
    "/career",
    "/career/",
    "/jobs",
    "/jobs/",
    "/all-jobs",
    "/all-jobs/",
    "/search",
    "/search/",
    "/positions",
    "/positions/",
    "/openings",
    "/openings/",
    "/apply",
    "/apply/",
    "/en/careers",
    "/de/careers",
    "/en/jobs",
    "/de/jobs",
}

_JOB_QUERY_PARAMS = {
    "id",
    "job_id",
    "jobid",
    "jid",
    "req",
    "req_id",
    "requisition_id",
    "gh_jid",
    "posting_id",
    "opening_id",
}


def validate_url(url: str) -> bool:
    """Validate URL conforms to safe HTTP(S) syntax without credentials or control characters."""
    if not url or not isinstance(url, str):
        return False

    # Reject control characters
    if re.search(r"[\r\n\t\x00-\x1f\x7f]", url):
        return False

    try:
        parsed = urlsplit(url)
    except Exception:
        return False

    if parsed.scheme.lower() not in ("http", "https"):
        return False

    if not parsed.netloc:
        return False

    # Reject credentials/userinfo
    if "@" in parsed.netloc or parsed.username or parsed.password:
        return False

    # Validate port if present
    try:
        _ = parsed.port
    except ValueError:
        return False

    return True


def is_job_specific_url(url: str) -> bool:
    """Classify whether a URL is job-specific rather than a generic careers/search page."""
    if not validate_url(url):
        return False

    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    path_lower = parsed.path.lower().rstrip("/")
    query = parse_qs(parsed.query, keep_blank_values=True)

    # Check if query contains explicit job identifier parameter
    query_keys_lower = {k.lower() for k in query.keys()}
    if any(param in query_keys_lower for param in _JOB_QUERY_PARAMS):
        return True

    # If path is generic careers root and no job query parameter, it is not job-specific
    if path_lower in _GENERIC_CAREERS_PATHS or not path:
        return False

    # Look for specific job segments in path: e.g. /jobs/12345, /o/123, /position/abc-123
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 2:
        parent = segments[-2].lower()
        child = segments[-1]
        if parent in ("jobs", "job", "positions", "position", "o", "p", "openings", "careers"):
            # If child has digits or is distinct from generic keywords
            if any(ch.isdigit() for ch in child) or len(child) > 3:
                return True

    # Single segment that contains digits and is not generic
    if len(segments) == 1:
        seg = segments[0]
        if any(ch.isdigit() for ch in seg) and seg.lower() not in _GENERIC_CAREERS_PATHS:
            return True

    return False


def are_urls_equivalent(url1: str | None, url2: str | None) -> bool:
    """Conservative URL comparison preserving original query structure."""
    if url1 is None or url2 is None:
        return False

    if url1 == url2:
        return True

    if not validate_url(url1) or not validate_url(url2):
        return False

    p1 = urlsplit(url1)
    p2 = urlsplit(url2)

    # Must share scheme, normalized netloc (lowercase, default ports stripped), path, and query
    p1_port = p1.port or (443 if p1.scheme == "https" else 80)
    p2_port = p2.port or (443 if p2.scheme == "https" else 80)
    p1_host = p1.hostname.lower() if p1.hostname else ""
    p2_host = p2.hostname.lower() if p2.hostname else ""

    return (
        p1.scheme.lower() == p2.scheme.lower()
        and p1_host == p2_host
        and p1_port == p2_port
        and p1.path == p2.path
        and p1.query == p2.query
    )

