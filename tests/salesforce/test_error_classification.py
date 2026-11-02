"""Tests for error classification, quota precedence, and recovery actions (SFCLIENT-01-S05)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.salesforce import (
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
)
from job_automation.salesforce.errors import (
    classify_gateway_failure,
    parse_salesforce_error_body,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "salesforce"


def test_quota_precedence_over_generic_403() -> None:
    """Verify that a 403 containing REQUEST_LIMIT_EXCEEDED is classified as RATE_LIMIT."""
    body = (FIXTURES_DIR / "error_request_limit_exceeded.json").read_bytes()
    failure = classify_gateway_failure(
        operation_kind=OperationKind.QUERY_PAGE,
        status_code=403,
        body=body,
        uncertain_transmission=False,
        attempts=[],
    )

    assert failure.error.category == ErrorCategory.RATE_LIMIT
    assert failure.safe_provider_code == "REQUEST_LIMIT_EXCEEDED"
    assert failure.recovery_action == RecoveryAction.RETRY_LATER
    assert failure.remote_outcome == RemoteOutcome.REJECTED


def test_permission_denial_on_403_without_quota() -> None:
    """Verify that 403 with permission error code is classified as PERMISSION."""
    body = (FIXTURES_DIR / "error_insufficient_access.json").read_bytes()
    failure = classify_gateway_failure(
        operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
        status_code=403,
        body=body,
        uncertain_transmission=False,
        attempts=[],
    )

    assert failure.error.category == ErrorCategory.PERMISSION
    assert failure.safe_provider_code == "INSUFFICIENT_ACCESS_ON_CROSS_REFERENCE_ENTITY"
    assert failure.recovery_action == RecoveryAction.NONE
    assert failure.remote_outcome == RemoteOutcome.REJECTED


def test_invalid_session_on_401() -> None:
    """Verify that 401 with INVALID_SESSION_ID is classified as AUTHENTICATION."""
    body = (FIXTURES_DIR / "error_invalid_session.json").read_bytes()
    failure = classify_gateway_failure(
        operation_kind=OperationKind.GET_RECORD,
        status_code=401,
        body=body,
        uncertain_transmission=False,
        attempts=[],
    )

    assert failure.error.category == ErrorCategory.AUTHENTICATION
    assert failure.safe_provider_code == "INVALID_SESSION_ID"
    assert failure.recovery_action == RecoveryAction.REAUTHORIZE


def test_storage_limit_exceeded_as_capacity() -> None:
    """Verify STORAGE_LIMIT_EXCEEDED maps to CAPACITY."""
    body = json.dumps([{"errorCode": "STORAGE_LIMIT_EXCEEDED", "message": "Storage limit reached"}]).encode("utf-8")
    failure = classify_gateway_failure(
        operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
        status_code=400,
        body=body,
        uncertain_transmission=False,
        attempts=[],
    )

    assert failure.error.category == ErrorCategory.CAPACITY
    assert failure.safe_provider_code == "STORAGE_LIMIT_EXCEEDED"
    assert failure.recovery_action == RecoveryAction.NONE


def test_uncertain_mutation_maps_to_unknown_and_reconcile() -> None:
    """Verify that uncertain transmission on mutation maps to UNKNOWN outcome and RECONCILE action."""
    failure = classify_gateway_failure(
        operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
        status_code=500,
        body=b"<html>Server Error</html>",
        uncertain_transmission=True,
        attempts=[],
    )

    assert failure.error.category == ErrorCategory.TRANSIENT_SERVICE
    assert failure.remote_outcome == RemoteOutcome.UNKNOWN
    assert failure.recovery_action == RecoveryAction.RECONCILE


def test_non_json_error_body_does_not_leak_raw_html() -> None:
    """Verify non-JSON HTML error body maps safely to generic safe code without leaking HTML."""
    html_body = b"<html><head><title>Bad Gateway</title></head><body>Proxy 10.0.0.1 error</body></html>"
    failure = classify_gateway_failure(
        operation_kind=OperationKind.GET_RECORD,
        status_code=502,
        body=html_body,
        uncertain_transmission=False,
        attempts=[],
    )

    assert failure.error.category == ErrorCategory.TRANSIENT_SERVICE
    assert failure.safe_provider_code == "server_error_502"
    assert "Proxy 10.0.0.1" not in failure.error.message
    assert "<html>" not in failure.error.message


def test_oauth_error_object_parsing() -> None:
    """Verify OAuth error format is parsed properly."""
    oauth_body = b'{"error": "invalid_grant", "error_description": "authentication failure"}'
    code, _ = parse_salesforce_error_body(oauth_body)
    assert code == "invalid_grant"

    failure = classify_gateway_failure(
        operation_kind=OperationKind.CHECK_CONNECTION,
        status_code=400,
        body=oauth_body,
        uncertain_transmission=False,
        attempts=[],
    )
    assert failure.error.category == ErrorCategory.AUTHENTICATION
    assert failure.safe_provider_code == "invalid_grant"
    assert failure.recovery_action == RecoveryAction.REAUTHORIZE

