"""Tests for conservative URL validation, comparison, and job-specificity classification."""

from __future__ import annotations

from job_automation.identity.urls import (
    are_urls_equivalent,
    is_job_specific_url,
    validate_url,
)


class TestUrls:
    def test_url_validation_rejection(self) -> None:
        # Control characters rejected
        assert not validate_url("https://example.com/jobs\n")
        assert not validate_url("https://example.com/jobs\r123")
        assert not validate_url("https://example.com/\x00test")

        # Credentials / userinfo rejected
        assert not validate_url("https://user:pass@example.com/jobs")
        assert not validate_url("https://admin@example.com/apply")

        # Non-HTTP(S) rejected
        assert not validate_url("ftp://example.com/job.txt")
        assert not validate_url("javascript:alert(1)")
        assert not validate_url("file:///C:/jobs/1.html")

        # Valid URLs
        assert validate_url("https://example.com/jobs/12345")
        assert validate_url("http://localhost:8080/careers/view?id=99")

    def test_job_specific_url_classification(self) -> None:
        # Generic careers pages are NOT job-specific
        assert not is_job_specific_url("https://example.com/careers")
        assert not is_job_specific_url("https://example.com/careers/")
        assert not is_job_specific_url("https://example.com/jobs")
        assert not is_job_specific_url("https://example.com/all-jobs")
        assert not is_job_specific_url("https://example.com/search")
        assert not is_job_specific_url("https://example.com/apply")

        # Job-specific URLs
        assert is_job_specific_url("https://example.com/jobs/12345")
        assert is_job_specific_url("https://example.com/careers/software-engineer-54321")
        assert is_job_specific_url("https://example.com/viewjob?job_id=98765")
        assert is_job_specific_url("https://boards.greenhouse.io/acme/jobs/45678")
        assert is_job_specific_url("https://example.com/positions?id=42")

    def test_conservative_url_equivalence(self) -> None:
        # Identical
        assert are_urls_equivalent(
            "https://example.com/jobs/1",
            "https://example.com/jobs/1",
        )

        # Case normalization for hostname only
        assert are_urls_equivalent(
            "https://EXAMPLE.COM/jobs/1",
            "https://example.com/jobs/1",
        )

        # Different paths remain distinct
        assert not are_urls_equivalent(
            "https://example.com/Jobs/1",
            "https://example.com/jobs/1",
        )

        # Different query parameters remain distinct
        assert not are_urls_equivalent(
            "https://example.com/jobs?id=1",
            "https://example.com/jobs?id=2",
        )

        # None values return False
        assert not are_urls_equivalent(None, "https://example.com")
        assert not are_urls_equivalent("https://example.com", None)

