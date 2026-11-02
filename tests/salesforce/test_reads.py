"""Tests for typed read operations and query pagination (SFCLIENT-01-S04)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.salesforce import (
    ConnectionCheckRequest,
    DescribeObjectRequest,
    GetRecordRequest,
    LimitsRequest,
    OperationKind,
    QueryPageRequest,
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
        expected_org_id="00D000000000001",
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
    token_provider = OAuthTokenProvider(settings, store, transport, clock=None)  # type: ignore[arg-type]
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
    )
    return client, transport


def test_connection_check_success(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify check_connection validates identity against userinfo endpoint."""
    client, transport = test_setup
    userinfo_fixture = (FIXTURES_DIR / "userinfo_success.json").read_bytes()
    transport.queue_response(status_code=200, body=userinfo_fixture)

    req = ConnectionCheckRequest(expected_org_id="00D000000000001")
    result = client.check_connection(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.connected is True
    assert result.value.org_id == "00D000000000001"
    assert result.value.user_id == "005000000000001"
    assert result.value.api_version == "v60.0"


def test_connection_check_org_id_mismatch_fails(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify check_connection fails if org ID does not match expected org."""
    client, transport = test_setup
    userinfo_fixture = json.dumps({
        "organization_id": "00DWRONG0000001",
        "user_id": "005000000000001",
    }).encode("utf-8")
    transport.queue_response(status_code=200, body=userinfo_fixture)

    req = ConnectionCheckRequest(expected_org_id="00D000000000001")
    result = client.check_connection(req)

    assert result.is_failure
    assert result.failure is not None
    assert "does not match expected" in result.failure.error.message


def test_get_limits_success(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify get_limits parses daily API request limits."""
    client, transport = test_setup
    limits_fixture = (FIXTURES_DIR / "limits_success.json").read_bytes()
    transport.queue_response(status_code=200, body=limits_fixture)

    result = client.get_limits(LimitsRequest())
    assert result.is_success
    assert result.value is not None
    assert result.value.daily_api_requests_max == 15000
    assert result.value.daily_api_requests_remaining == 14950


def test_describe_object_success(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify describe_object parses object metadata and external ID flags."""
    client, transport = test_setup
    describe_fixture = (FIXTURES_DIR / "describe_job_success.json").read_bytes()
    transport.queue_response(status_code=200, body=describe_fixture)

    result = client.describe_object(DescribeObjectRequest(object_name="Job__c"))
    assert result.is_success
    assert result.value is not None
    assert result.value.object_name == "Job__c"
    assert result.value.custom is True
    assert "External_Id__c" in result.value.fields
    assert result.value.fields["External_Id__c"].external_id is True
    assert "External_Id__c" in result.value.external_id_fields


def test_get_record_by_id_success(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify get_record retrieves record by standard record ID."""
    client, transport = test_setup
    transport.queue_response(
        status_code=200,
        body=json.dumps({"Id": "a00000000000001AAA", "Title__c": "Senior Python Engineer"}).encode("utf-8"),
    )

    req = GetRecordRequest(
        object_name="Job__c",
        record_id="a00000000000001AAA",
        fields=["Id", "Title__c"],
    )
    result = client.get_record(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.record_id == "a00000000000001AAA"
    assert result.value.fields["Title__c"] == "Senior Python Engineer"

    # Check request URL
    req_sent = transport.requests[-1]
    assert req_sent.method == "GET"
    assert "/services/data/v60.0/sobjects/Job__c/a00000000000001AAA?fields=Id%2CTitle__c" in req_sent.url


def test_get_record_404_returns_safe_not_found(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify 404 returns permanent not-found failure rather than empty record."""
    client, transport = test_setup
    transport.queue_response(
        status_code=404,
        body=json.dumps([{"errorCode": "NOT_FOUND", "message": "The requested resource does not exist"}]).encode("utf-8"),
    )

    req = GetRecordRequest(
        object_name="Job__c",
        record_id="a00000000000001AAA",
        fields=["Id"],
    )
    result = client.get_record(req)

    assert result.is_failure
    assert result.failure is not None
    assert result.failure.http_status == 404
    assert result.failure.safe_provider_code == "NOT_FOUND"
    assert result.failure.error.category == ErrorCategory.VALIDATION


def test_query_page_first_and_continuation(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify multi-page query with continuation URL."""
    client, transport = test_setup
    first_page_fixture = (FIXTURES_DIR / "query_page_first.json").read_bytes()
    second_page_fixture = (FIXTURES_DIR / "query_page_success.json").read_bytes()

    transport.queue_response(status_code=200, body=first_page_fixture)
    transport.queue_response(status_code=200, body=second_page_fixture)

    # 1. First page
    q1 = QueryPageRequest(soql="SELECT Id, Title__c FROM Job__c")
    res1 = client.query_page(q1)
    assert res1.is_success
    assert res1.value is not None
    assert res1.value.done is False
    assert res1.value.next_records_url == "/services/data/v60.0/query/01g000000000001-500"
    assert len(res1.value.records) == 1

    # 2. Continuation page
    q2 = QueryPageRequest(continuation_token=res1.value.next_records_url)
    res2 = client.query_page(q2)
    assert res2.is_success
    assert res2.value is not None
    assert res2.value.done is True
    assert len(res2.value.records) == 2


def test_query_page_rejects_foreign_continuation_host(
    test_setup: tuple[SalesforceGatewayV2Client, FakeSalesforceTransport]
) -> None:
    """Verify continuation token attempting to redirect to foreign origin fails before I/O."""
    client, transport = test_setup
    foreign_continuation = "https://evil.attacker.com/services/data/v60.0/query/01g000000000001-500"
    req = QueryPageRequest(continuation_token=foreign_continuation)
    result = client.query_page(req)

    assert result.is_failure
    assert result.failure is not None
    assert result.failure.safe_provider_code == "invalid_continuation_token"
    # No request sent for malicious continuation
    assert len(transport.requests) == 0
