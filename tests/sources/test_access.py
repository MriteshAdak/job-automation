"""Tests for access authorization review validation (SOURCE-01-S03)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.access import validate_access_review
from job_automation.sources.errors import (
    ERR_ACCESS_DENIED,
    ERR_ACCESS_EXPIRED,
    ERR_ACCESS_METHOD_MISMATCH,
    ERR_ACCESS_UNREVIEWED,
)
from job_automation.sources.models import AccessReviewStatus

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sources"


class TestAccessReviewValidation:
    def test_prose_access_notes_alone_do_not_grant_permission(self) -> None:
        """Verify arbitrary prose like 'public website' or 'Max 1 req/sec' is UNREVIEWED."""
        config = SourceConfig(
            source_key="prose_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            access_rules="public website; robots.txt allows /jobs; max 1 req/sec",
            enabled=True,
        )
        review, issues = validate_access_review(config)
        assert review.status == AccessReviewStatus.UNREVIEWED
        assert review.notes == "public website; robots.txt allows /jobs; max 1 req/sec"
        assert any(i.code == ERR_ACCESS_UNREVIEWED for i in issues)

    def test_null_access_rules_is_unreviewed(self) -> None:
        """Verify null access_rules produces UNREVIEWED status."""
        config = SourceConfig(
            source_key="null_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            access_rules=None,
            enabled=False,
        )
        review, issues = validate_access_review(config)
        assert review.status == AccessReviewStatus.UNREVIEWED
        assert any(i.code == ERR_ACCESS_UNREVIEWED for i in issues)

    def test_explicit_denied_access_produces_denied(self) -> None:
        """Verify explicit denied review is identified and flagged with ERR_ACCESS_DENIED."""
        config = SourceConfig(
            source_key="denied_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            access_rules="denied",
        )
        review, issues = validate_access_review(config)
        assert review.status == AccessReviewStatus.DENIED
        assert any(i.code == ERR_ACCESS_DENIED for i in issues)

    def test_structured_permitted_review_validates(self) -> None:
        """Verify structured JSON review with valid timestamp and evidence passes."""
        review_json = json.dumps(
            {
                "status": "permitted",
                "reviewed_at": "2026-10-28T00:00:00Z",
                "evidence_ref": "official-api-license-v1",
                "permitted_methods": ["api"],
                "restrictions": ["no-resale", "max-100-req-per-day"],
            }
        )
        config = SourceConfig(
            source_key="permitted_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            access_rules=review_json,
        )
        review, issues = validate_access_review(config)
        assert review.status == AccessReviewStatus.PERMITTED
        assert review.evidence_ref == "official-api-license-v1"
        assert review.permitted_methods == [AcquisitionMethod.API]
        assert review.restrictions == ["no-resale", "max-100-req-per-day"]
        assert len(issues) == 0

    def test_acquisition_method_mismatch_fails_permitted(self) -> None:
        """Verify permission for 'api' does not grant 'permitted_scraping'."""
        review_json = json.dumps(
            {
                "status": "permitted",
                "reviewed_at": "2026-10-28T00:00:00Z",
                "evidence_ref": "api-only-agreement",
                "permitted_methods": ["api"],
            }
        )
        config = SourceConfig(
            source_key="mismatch_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.PERMITTED_SCRAPING,
            base_url="https://careers.test.invalid/jobs",
            access_rules=review_json,
        )
        review, issues = validate_access_review(config)
        assert review.status == AccessReviewStatus.UNREVIEWED
        assert any(i.code == ERR_ACCESS_METHOD_MISMATCH for i in issues)

    def test_expired_access_review_fails(self) -> None:
        """Verify access review with past expires_at timestamp is flagged as expired."""
        review_json = json.dumps(
            {
                "status": "permitted",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "expires_at": "2025-12-31T23:59:59Z",
                "evidence_ref": "expired-license",
                "permitted_methods": ["api"],
            }
        )
        config = SourceConfig(
            source_key="expired_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            access_rules=review_json,
        )
        review, issues = validate_access_review(config)
        assert review.status == AccessReviewStatus.DENIED
        assert any(i.code == ERR_ACCESS_EXPIRED for i in issues)

