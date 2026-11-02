"""Tests for typed record mutations (upsert and update) and payload preservation (SFCLIENT-01-S04)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.salesforce import (
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
    UpdateRequest,
    UpsertRequest,
)
from job_automation.salesforce.auth import OAuthTokenProvider
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.credentials import InMemoryCredentialStore
from job_automation.salesforce.gateway import SalesforceGatewayV2Client
from tests.fakes.salesforce_transport import FakeSalesforceTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "salesforce"


@pytest.fixture
def test_setup() -> tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]:
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "test_client_id",
        "sf/refresh_token": "test_refresh_token",
    })
    transport = FakeSalesforceTransport()
    # Queue initial token response
    transport.queue_response(
        status_code=200,
        body=json.dumps({
            "access_token": "valid_token_123",
            "instance_url": "https://test.my.salesforce.com",
            "token_type": "Bearer",
        }).encode("utf-8"),
    )
    token_provider = OAuthTokenProvider(settings, store, transport)
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
    )
    return client, transport


def test_upsert_201_created_success(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify 201 Created upsert response returns record ID and created=True."""
    client, transport = test_setup
    upsert_fixture = (FIXTURES_DIR / "upsert_created_201.json").read_bytes()
    transport.queue_response(status_code=201, body=upsert_fixture)

    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-job-001",
        fields={"Title__c": "Staff Engineer", "Score__c": 92.0},
    )
    result = client.upsert_by_external_id(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.created is True
    assert result.value.record_id == "a00000000000001AAA"
    assert result.value.external_id_value == "ext-job-001"

    # Verify HTTP request
    req_sent = transport.requests[-1]
    assert req_sent.method == "PATCH"
    assert (
        "/services/data/v60.0/sobjects/Job__c/External_Id__c/ext-job-001"
        in req_sent.url
    )
    body_data = json.loads(req_sent.body.decode("utf-8"))  # type: ignore[union-attr]
    assert body_data == {"Title__c": "Staff Engineer", "Score__c": 92.0}


def test_upsert_200_updated_success(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify 200 OK upsert response returns record ID and created=False."""
    client, transport = test_setup
    upsert_fixture = (FIXTURES_DIR / "upsert_updated_200.json").read_bytes()
    transport.queue_response(status_code=200, body=upsert_fixture)

    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-job-001",
        fields={"Title__c": "Principal Engineer"},
    )
    result = client.upsert_by_external_id(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.created is False
    assert result.value.record_id == "a00000000000001AAA"


def test_upsert_duplicate_300_multiple_choices_fails_permanently(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify 300 Multiple Choices reports duplicate ambiguity and stops without retry."""
    client, transport = test_setup
    transport.queue_response(
        status_code=300,
        body=b'["/services/data/v60.0/sobjects/Job__c/a001", "/services/data/v60.0/sobjects/Job__c/a002"]',
    )

    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-duplicate",
        fields={"Title__c": "Engineer"},
    )
    result = client.upsert_by_external_id(req)

    assert result.is_failure
    assert result.failure is not None
    assert result.failure.http_status == 300
    assert result.failure.safe_provider_code == "multiple_external_id_matches"
    assert result.failure.remote_outcome == RemoteOutcome.REJECTED
    assert result.failure.recovery_action == RecoveryAction.NONE


def test_update_record_204_success(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify update_record handles 204 No Content acknowledgment."""
    client, transport = test_setup
    transport.queue_response(status_code=204, body=b"")

    req = UpdateRequest(
        object_name="Job__c",
        record_id="a00000000000001AAA",
        fields={"Title__c": "Updated Title"},
    )
    result = client.update_record(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.record_id == "a00000000000001AAA"
    assert result.value.acknowledged_at is not None

    req_sent = transport.requests[-1]
    assert req_sent.method == "PATCH"
    assert "/services/data/v60.0/sobjects/Job__c/a00000000000001AAA" in req_sent.url
    body_data = json.loads(req_sent.body.decode("utf-8"))  # type: ignore[union-attr]
    assert body_data == {"Title__c": "Updated Title"}


def test_update_record_invalid_id_rejected_before_io(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify malformed record IDs are rejected before transport."""
    with pytest.raises(ValueError, match="Invalid Salesforce record ID"):
        UpdateRequest(
            object_name="Job__c",
            record_id="invalid_short_id",
            fields={"Title__c": "Engineer"},
        )

