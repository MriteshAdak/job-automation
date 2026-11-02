"""Tests for acquisition method validation (SOURCE-01-S04)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import ERR_INVALID_ENDPOINT
from job_automation.sources.request_policy import validate_request_policy


class TestAcquisitionMethodValidation:
    def test_api_requires_https_or_loopback(self) -> None:
        """Verify API acquisition rejects insecure non-loopback HTTP."""
        config_insecure = SourceConfig(
            source_key="insecure_api",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="http://api.external.invalid/jobs",
        )
        _, issues = validate_request_policy(config_insecure)
        assert any(i.code == ERR_INVALID_ENDPOINT for i in issues)

        config_loopback = SourceConfig(
            source_key="loopback_api",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="http://localhost:8080/jobs",
        )
        _, issues_loop = validate_request_policy(config_loopback)
        assert len(issues_loop) == 0

    def test_manual_import_accepts_provenance_uri(self) -> None:
        """Verify manual_import accepts file URI, custom URI, or provenance URL."""
        config_custom = SourceConfig(
            source_key="manual_custom",
            provider="manual",
            board_id="inbox",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://inbox/pasted_document",
        )
        _, issues_custom = validate_request_policy(config_custom)
        assert len(issues_custom) == 0

        config_file = SourceConfig(
            source_key="manual_file",
            provider="manual",
            board_id="csv_import",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="file:///C:/Users/Example/jobs.csv",
        )
        _, issues_file = validate_request_policy(config_file)
        assert len(issues_file) == 0

    def test_manual_import_does_not_require_http_policy(self) -> None:
        """Verify manual_import succeeds with an empty request_policy dictionary."""
        config = SourceConfig(
            source_key="manual_empty",
            provider="manual",
            board_id="inbox",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://inbox/text",
            request_policy={},
        )
        policy, issues = validate_request_policy(config)
        assert len(issues) == 0
        assert policy.timeout_seconds == 30.0

