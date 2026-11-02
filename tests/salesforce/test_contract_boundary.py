"""Tests for SFCLIENT-01 contracts, protocol conformance, and validation boundaries."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGateway, SalesforceGatewayV2
from job_automation.contracts.salesforce import (
    AttemptSummary,
    ConnectionCheckRequest,
    ConnectionCheckResult,
    DescribeFieldResult,
    DescribeObjectRequest,
    DescribeObjectResult,
    GatewayFailure,
    GatewayResult,
    GetRecordRequest,
    GetRecordResult,
    LimitsRequest,
    LimitsResult,
    OperationKind,
    QueryPageRequest,
    QueryPageResult,
    RecoveryAction,
    RemoteOutcome,
    UpdateRequest,
    UpdateResult,
    UpsertRequest,
    UpsertResult,
    validate_bounded_json_value,
    validate_salesforce_identifier,
)
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.gateway import SalesforceGatewayV2Client
from job_automation.salesforce.credentials import InMemoryCredentialStore
from job_automation.salesforce.auth import OAuthTokenProvider
from tests.fakes.fake_services import FakeSalesforceGateway
from tests.fakes.salesforce_transport import FakeSalesforceTransport


def test_salesforce_gateway_v2_protocol_conformance() -> None:
    """Verify that SalesforceGatewayV2Client satisfies SalesforceGatewayV2 protocol."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="cid",
        credential_ref="cred",
    )
    transport = FakeSalesforceTransport()
    store = InMemoryCredentialStore({"cid": "client123", "cred": "refresh123"})
    token_provider = OAuthTokenProvider(settings, store, transport, clock=None)  # type: ignore[arg-type]
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
    )
    assert isinstance(client, SalesforceGatewayV2)


def test_legacy_salesforce_gateway_protocol_intact() -> None:
    """Verify legacy SalesforceGateway protocol remains intact and satisfied by foundation fake."""
    fake = FakeSalesforceGateway()
    assert isinstance(fake, SalesforceGateway)
    # V2 client does NOT pretend to conform to legacy domain sync boundary
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
    )
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=FakeSalesforceTransport(),
        token_provider=None,  # type: ignore[arg-type]
    )
    assert not isinstance(client, SalesforceGateway)


def test_gateway_result_strict_exclusivity() -> None:
    """Verify that GatewayResult enforces exact XOR exclusivity between value and failure."""
    # 1. Success valid
    res_ok = GatewayResult.success("record_id_123")
    assert res_ok.is_success
    assert not res_ok.is_failure
    assert res_ok.value == "record_id_123"

    # 2. Failure valid
    fail = GatewayFailure(
        error=ClassifiedError.from_category(ErrorCategory.AUTHENTICATION, "Token expired"),
        operation_kind=OperationKind.GET_RECORD,
        remote_outcome=RemoteOutcome.NOT_SENT,
        recovery_action=RecoveryAction.REAUTHORIZE,
    )
    res_fail = GatewayResult.fail(fail)
    assert res_fail.is_failure
    assert not res_fail.is_success
    assert res_fail.failure == fail

    # 3. Neither raises ValueError
    with pytest.raises(ValueError, match="exactly one of 'value' or 'failure'"):
        GatewayResult(value=None, failure=None)

    # 4. Both raises ValueError
    with pytest.raises(ValueError, match="exactly one of 'value' or 'failure'"):
        GatewayResult(value="val", failure=fail)


def test_bounded_json_value_validation() -> None:
    """Verify bounded JSON recursion depth, finite floats, and size limits."""
    # Finite floats accepted
    assert validate_bounded_json_value({"score": 98.5}) == {"score": 98.5}

    # NaN / Inf rejected
    with pytest.raises(ValueError, match="Floats must be finite"):
        validate_bounded_json_value({"nan": float("nan")})

    with pytest.raises(ValueError, match="Floats must be finite"):
        validate_bounded_json_value({"inf": float("inf")})

    # Deep nesting rejected (> 5 levels)
    deep: dict = {"level": 1}
    curr = deep
    for i in range(2, 8):
        curr["child"] = {"level": i}
        curr = curr["child"]

    with pytest.raises(ValueError, match="maximum allowable nesting depth"):
        validate_bounded_json_value(deep)


def test_salesforce_identifier_validation() -> None:
    """Verify API identifier validation for objects and fields."""
    # Valid standard & custom names
    assert validate_salesforce_identifier("Job__c") == "Job__c"
    assert validate_salesforce_identifier("Company__c") == "Company__c"
    assert validate_salesforce_identifier("External_Id__c") == "External_Id__c"
    assert validate_salesforce_identifier("Id") == "Id"
    assert validate_salesforce_identifier("Account") == "Account"

    # Invalid names
    with pytest.raises(ValueError, match="Invalid Salesforce"):
        validate_salesforce_identifier("123BadStart")

    with pytest.raises(ValueError, match="Invalid Salesforce"):
        validate_salesforce_identifier("Job-Name")

    with pytest.raises(ValueError, match="non-empty string"):
        validate_salesforce_identifier("")


def test_get_record_request_selector_exclusivity() -> None:
    """Verify GetRecordRequest rejects both or neither selector."""
    # Valid record_id
    req1 = GetRecordRequest(object_name="Job__c", record_id="a00000000000001", fields=["Id", "Title__c"])
    assert req1.record_id == "a00000000000001"

    # Valid external_id
    req2 = GetRecordRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext_100",
        fields=["Id"],
    )
    assert req2.external_id_value == "ext_100"

    # Neither provided -> rejected
    with pytest.raises(ValueError, match="must provide exactly one selector"):
        GetRecordRequest(object_name="Job__c", fields=["Id"])

    # Both provided -> rejected
    with pytest.raises(ValueError, match="must provide exactly one selector"):
        GetRecordRequest(
            object_name="Job__c",
            record_id="a00000000000001",
            external_id_field="External_Id__c",
            external_id_value="ext_100",
            fields=["Id"],
        )


def test_query_page_request_selector_exclusivity() -> None:
    """Verify QueryPageRequest rejects both or neither SOQL and continuation."""
    # Valid soql
    q1 = QueryPageRequest(soql="SELECT Id FROM Job__c")
    assert q1.soql == "SELECT Id FROM Job__c"

    # Valid continuation
    q2 = QueryPageRequest(continuation_token="/services/data/v60.0/query/01g000000000001-500")
    assert q2.continuation_token is not None

    # Neither
    with pytest.raises(ValueError, match="must supply either 'soql' for initial page OR 'continuation_token'"):
        QueryPageRequest()

    # Both
    with pytest.raises(ValueError, match="must supply either 'soql' for initial page OR 'continuation_token'"):
        QueryPageRequest(
            soql="SELECT Id FROM Job__c",
            continuation_token="/services/data/v60.0/query/01g000000000001-500",
        )


def test_request_payload_immutability() -> None:
    """Verify request fields cannot be mutated post-instantiation."""
    fields = {"Title__c": "Engineer"}
    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-1",
        fields=fields,
    )
    # ContractModel is frozen
    with pytest.raises(Exception):
        req.object_name = "Other__c"  # type: ignore[misc]

    # Mutating original dict should not affect request if deep copied or read
    fields["Title__c"] = "Modified"
    # Even if caller mutates original dict, frozen request preserves its bound dictionary
    # (ContractModel validation constructs a copy of fields)
    assert req.fields["Title__c"] == "Engineer"

