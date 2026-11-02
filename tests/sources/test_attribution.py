"""Tests for attribution rules and notices validation (SOURCE-01-S03)."""

from __future__ import annotations

import json

import pytest

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.access import validate_attribution_review
from job_automation.sources.errors import (
    ERR_ATTRIBUTION_MISSING_NOTICE,
    ERR_ATTRIBUTION_UNKNOWN,
)
from job_automation.sources.models import AttributionStatus


class TestAttributionValidation:
    def test_null_attribution_is_unknown(self) -> None:
        """Verify null attribution_rules produces UNKNOWN status and diagnostic issue."""
        config = SourceConfig(
            source_key="null_attrib",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            attribution_rules=None,
            enabled=True,
        )
        attrib, issues = validate_attribution_review(config)
        assert attrib.status == AttributionStatus.UNKNOWN
        assert any(i.code == ERR_ATTRIBUTION_UNKNOWN for i in issues)

    def test_none_required_attribution_passes(self) -> None:
        """Verify explicit 'none_required' or 'none' satisfies attribution without issues."""
        config = SourceConfig(
            source_key="none_req",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            attribution_rules="none_required",
        )
        attrib, issues = validate_attribution_review(config)
        assert attrib.status == AttributionStatus.NONE_REQUIRED
        assert len(issues) == 0

    def test_plain_text_attribution_notice_preserved(self) -> None:
        """Verify plain-text attribution string is marked REQUIRED and notice preserved."""
        notice_text = "Source: Sample Employer Career Portal"
        config = SourceConfig(
            source_key="text_attrib",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            attribution_rules=notice_text,
        )
        attrib, issues = validate_attribution_review(config)
        assert attrib.status == AttributionStatus.REQUIRED
        assert attrib.notice == notice_text
        assert len(issues) == 0

    def test_structured_json_attribution_preserves_notice_and_link(self) -> None:
        """Verify structured JSON attribution preserves notice, link, and notes."""
        attrib_json = json.dumps(
            {
                "status": "required",
                "notice": "Data provided by Partner API",
                "link": "https://partner.invalid/attribution",
                "notes": "Display with link on every view",
            }
        )
        config = SourceConfig(
            source_key="json_attrib",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            attribution_rules=attrib_json,
        )
        attrib, issues = validate_attribution_review(config)
        assert attrib.status == AttributionStatus.REQUIRED
        assert attrib.notice == "Data provided by Partner API"
        assert attrib.link == "https://partner.invalid/attribution"
        assert len(issues) == 0

    def test_missing_notice_in_required_attribution_fails(self) -> None:
        """Verify structured attribution with status required but missing notice raises issue."""
        attrib_json = json.dumps({"status": "required", "link": "https://partner.invalid"})
        config = SourceConfig(
            source_key="missing_notice",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            attribution_rules=attrib_json,
        )
        attrib, issues = validate_attribution_review(config)
        assert any(i.code == ERR_ATTRIBUTION_MISSING_NOTICE for i in issues)

