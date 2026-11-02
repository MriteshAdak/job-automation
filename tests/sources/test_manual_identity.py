"""Tests for conservative manual posting identity derivation and URL validation (SOURCE-02-S03)."""

from __future__ import annotations

import hashlib
import pytest

from job_automation.sources.adapters.manual_identity import (
    derive_manual_posting_id,
    validate_http_url,
)


def test_validate_http_url_valid() -> None:
    valid_urls = [
        "https://example.com/jobs/123",
        "http://sub.domain.org/vacancies?dept=eng&id=42",
        "https://jobs.company.invalid/vacancies/0007",
    ]
    for url in valid_urls:
        is_valid, err = validate_http_url(url)
        assert is_valid, f"Expected {url} to be valid, got error: {err}"
        assert err is None


def test_validate_http_url_invalid() -> None:
    cases = [
        ("", "missing_url"),
        ("   ", "missing_url"),
        (" https://example.com", "invalid_url_format"),
        ("https://example.com ", "invalid_url_format"),
        ("ftp://ftp.example.com/job", "invalid_url_scheme"),
        ("file:///C:/path/to/job.txt", "invalid_url_scheme"),
        ("javascript:alert(1)", "invalid_url_scheme"),
        ("https://", "missing_url_host"),
        ("https://user:password@example.com/job", "url_has_credentials"),
    ]
    for url, expected_err in cases:
        is_valid, err = validate_http_url(url)
        assert not is_valid, f"Expected {url} to be invalid"
        assert err == expected_err


def test_derive_manual_posting_id_explicit_preserves_zeros_and_case() -> None:
    explicit_ids = ["0007", "Job-XYZ_42", "000000"]
    url = "https://jobs.example.invalid/job"
    for exp in explicit_ids:
        posting_id, method = derive_manual_posting_id(exp, url)
        assert posting_id == exp
        assert method == "explicit_id"


def test_derive_manual_posting_id_url_fallback() -> None:
    url = "https://jobs.example.invalid/vacancies/senior-developer"
    posting_id, method = derive_manual_posting_id(None, url)
    assert method == "url_fallback_v1"
    expected_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    assert posting_id == f"url-v1:{expected_hash}"

    # Also works when explicit_id is empty string
    empty_id_posting, empty_method = derive_manual_posting_id("", url)
    assert empty_id_posting == f"url-v1:{expected_hash}"
    assert empty_method == "url_fallback_v1"


def test_derive_manual_posting_id_invalid_url_raises() -> None:
    with pytest.raises(ValueError, match="Cannot derive URL identity from invalid URL"):
        derive_manual_posting_id(None, "ftp://invalid-url")

