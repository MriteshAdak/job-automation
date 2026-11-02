"""Tests for secret redaction, safe diagnostics logging, and recorder isolation (SFCLIENT-01-S06)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from job_automation.contracts.salesforce import (
    GetRecordRequest,
    UpsertRequest,
)
from job_automation.salesforce.auth import OAuthTokenProvider
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.credentials import InMemoryCredentialStore
from job_automation.salesforce.diagnostics import (
    SafeMemoryDiagnosticsRecorder,
    redact_sensitive_text,
)
from job_automation.salesforce.gateway import SalesforceGatewayV2Client
from tests.fakes.salesforce_transport import FakeSalesforceTransport


def test_redact_sensitive_text_masks_all_credentials() -> None:
    """Verify redact_sensitive_text scrubs Bearer tokens, secrets, params, and private keys."""
    sample = (
        "Authorization: Bearer secret_access_token_12345\n"
        "POST https://login.salesforce.com?client_secret=super_secret_xyz&client_id=cid_1\n"
        "refresh_token=rt_secret_999\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
    )

    scrubbed = redact_sensitive_text(sample)

    assert "secret_access_token_12345" not in scrubbed
    assert "super_secret_xyz" not in scrubbed
    assert "rt_secret_999" not in scrubbed
    assert "MIIEowIBAAKCAQEA0" not in scrubbed

    assert "[REDACTED]" in scrubbed
    assert "client_secret=[REDACTED]" in scrubbed
    assert "refresh_token=[REDACTED]" in scrubbed
    assert "[REDACTED_PRIVATE_KEY]" in scrubbed

    # Standalone Bearer token string
    bearer_scrubbed = redact_sensitive_text("Authorization token: Bearer my_raw_token_value")
    assert bearer_scrubbed == "Authorization token: Bearer [REDACTED]"


def test_safe_recorder_captures_only_allowlisted_fields() -> None:
    """Verify diagnostic recorder receives allowlisted fields and no secret tokens or payloads."""
    recorder = SafeMemoryDiagnosticsRecorder()
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "client_abc",
        "sf/refresh_token": "secret_refresh_token_to_hide",
    })
    transport = FakeSalesforceTransport()
    # 1. Token response
    transport.queue_response(
        status_code=200,
        body=json.dumps({
            "access_token": "secret_access_token_to_hide",
            "instance_url": "https://test.my.salesforce.com",
        }).encode("utf-8"),
    )
    # 2. Upsert response
    transport.queue_response(
        status_code=201,
        body=json.dumps({"id": "a001", "success": True}).encode("utf-8"),
    )

    token_provider = OAuthTokenProvider(settings, store, transport)
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
        recorder=recorder,
    )

    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-123",
        fields={"Title__c": "Senior Staff Architect", "CandidateNote__c": "Confidential text"},
    )
    result = client.upsert_by_external_id(req)
    assert result.is_success

    # Inspect recorded diagnostic events
    assert len(recorder.events) > 0
    event = recorder.events[0]

    event_dict = event.model_dump(mode="json")
    # Allowlisted keys only
    allowed_keys = {
        "call_id",
        "operation_kind",
        "api_version",
        "attempt_number",
        "purpose",
        "http_status",
        "safe_code",
        "duration_ms",
        "remote_outcome",
        "recovery_action",
        "utc_timestamp",
        "quota_remaining",
        "schema_version",
    }
    assert set(event_dict.keys()).issubset(allowed_keys)

    # Serialize event and check that no secret or payload text appears
    event_json = json.dumps(event_dict)
    assert "secret_refresh_token_to_hide" not in event_json
    assert "secret_access_token_to_hide" not in event_json
    assert "Senior Staff Architect" not in event_json
    assert "Confidential text" not in event_json


def test_recorder_exception_does_not_break_operation_or_repeat_mutation() -> None:
    """Verify failing diagnostics recorder does not cause operation failure or duplicate execution."""
    broken_recorder = MagicMock()
    broken_recorder.record_event.side_effect = RuntimeError("Disk full in telemetry system")

    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "client_abc",
        "sf/refresh_token": "token_123",
    })
    transport = FakeSalesforceTransport()
    transport.queue_response(
        status_code=200,
        body=json.dumps({"access_token": "tok", "instance_url": "https://test.my.salesforce.com"}).encode("utf-8"),
    )
    transport.queue_response(
        status_code=204,
        body=b"",
    )

    token_provider = OAuthTokenProvider(settings, store, transport)
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
        recorder=broken_recorder,
    )

    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-123",
        fields={"Title__c": "Engineer"},
    )
    result = client.upsert_by_external_id(req)

    # Operation still succeeds!
    assert result.is_success
    assert result.value is not None
    # No duplicate requests were sent (1 token, 1 upsert = 2)
    assert len(transport.requests) == 2
