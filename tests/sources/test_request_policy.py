"""Tests for bounded request policy and endpoint validation (SOURCE-01-S04)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import (
    ERR_CONFLICTING_POLICY,
    ERR_DISALLOWED_CREDENTIAL,
    ERR_INVALID_ENDPOINT,
    ERR_INVALID_REQUEST_POLICY,
)
from job_automation.sources.request_policy import validate_request_policy


class TestRequestPolicyValidation:
    def test_legacy_timeout_mapped_to_timeout_seconds(self) -> None:
        """Verify legacy 'timeout' key is converted to timeout_seconds."""
        config = SourceConfig(
            source_key="leg_timeout",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"timeout": 45},
        )
        policy, issues = validate_request_policy(config)
        assert policy.timeout_seconds == 45.0
        assert len(issues) == 0

    def test_conflicting_timeout_keys_flagged(self) -> None:
        """Verify conflicting legacy 'timeout' and 'timeout_seconds' raise issue."""
        config = SourceConfig(
            source_key="conflict_timeout",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"timeout": 30, "timeout_seconds": 60},
        )
        policy, issues = validate_request_policy(config)
        assert any(i.code == ERR_CONFLICTING_POLICY for i in issues)

    def test_negative_or_zero_timeout_rejected(self) -> None:
        """Verify non-positive timeout values are rejected."""
        config = SourceConfig(
            source_key="neg_timeout",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"timeout_seconds": 0},
        )
        _, issues = validate_request_policy(config)
        assert any(i.code == ERR_INVALID_REQUEST_POLICY for i in issues)

    def test_boolean_timeout_rejected(self) -> None:
        """Verify boolean timeout is rejected."""
        config = SourceConfig(
            source_key="bool_timeout",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"timeout_seconds": True},
        )
        _, issues = validate_request_policy(config)
        assert any(i.code == ERR_INVALID_REQUEST_POLICY for i in issues)

    def test_unknown_policy_key_typo_rejected(self) -> None:
        """Verify typos like 'timeuot' are flagged as unknown policy keys."""
        config = SourceConfig(
            source_key="typo_key",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"timeuot": 30},
        )
        _, issues = validate_request_policy(config)
        assert any(i.code == ERR_INVALID_REQUEST_POLICY for i in issues)

    def test_rate_limit_converts_to_spacing(self) -> None:
        """Verify requests_per_minute converts to request_spacing_seconds."""
        config = SourceConfig(
            source_key="rpm_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"requests_per_minute": 30},
        )
        policy, issues = validate_request_policy(config)
        assert policy.request_spacing_seconds == 2.0
        assert len(issues) == 0

    def test_max_attempts_bounds(self) -> None:
        """Verify max_attempts bounds: rejects 0 and >10."""
        config_low = SourceConfig(
            source_key="att_low",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"max_attempts": 0},
        )
        _, issues_low = validate_request_policy(config_low)
        assert any(i.code == ERR_INVALID_REQUEST_POLICY for i in issues_low)

        config_high = SourceConfig(
            source_key="att_high",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"max_attempts": 20},
        )
        _, issues_high = validate_request_policy(config_high)
        assert any(i.code == ERR_INVALID_REQUEST_POLICY for i in issues_high)

    def test_forbidden_credentials_in_url_rejected(self) -> None:
        """Verify embedded userinfo credentials in base_url are rejected."""
        config = SourceConfig(
            source_key="cred_url",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://user:secrettoken@api.test.invalid/jobs",
        )
        _, issues = validate_request_policy(config)
        assert any(i.code == ERR_DISALLOWED_CREDENTIAL for i in issues)

    def test_forbidden_authorization_header_rejected(self) -> None:
        """Verify Authorization header in request_policy is rejected."""
        config = SourceConfig(
            source_key="cred_header",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"headers": {"Authorization": "Bearer 12345"}},
        )
        _, issues = validate_request_policy(config)
        assert any(i.code == ERR_DISALLOWED_CREDENTIAL for i in issues)

    def test_forbidden_api_key_parameter_rejected(self) -> None:
        """Verify api_key parameter in request_policy is rejected."""
        config = SourceConfig(
            source_key="cred_param",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"params": {"api_key": "secret123"}},
        )
        _, issues = validate_request_policy(config)
        assert any(i.code == ERR_DISALLOWED_CREDENTIAL for i in issues)

    def test_url_fragment_rejected(self) -> None:
        """Verify URL fragments in base_url are rejected."""
        config = SourceConfig(
            source_key="frag_url",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs#page1",
        )
        _, issues = validate_request_policy(config)
        assert any(i.code == ERR_INVALID_ENDPOINT for i in issues)

