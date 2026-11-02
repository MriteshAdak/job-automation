"""Tests for bounded budgets, Retry-After header parsing, and mutation replay policies (SFCLIENT-01-S05)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from job_automation.contracts.salesforce import (
    GetRecordRequest,
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
from job_automation.salesforce.ports import NoJitter
from job_automation.salesforce.transport import TransportError
from tests.fakes.salesforce_transport import FakeSalesforceTransport


class ScriptedClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.time = start

    def monotonic(self) -> float:
        return self.time

    def now_utc(self):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.time, timezone.utc)

    def advance(self, sec: float) -> None:
        self.time += sec


class ScriptedSleeper:
    def __init__(self, clock: ScriptedClock) -> None:
        self.clock = clock
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.advance(seconds)


@pytest.fixture
def test_env():
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
        max_total_sends=6,
        max_resource_sends=3,
        max_token_sends=2,
        initial_backoff_seconds=1.0,
        max_backoff_seconds=8.0,
        total_call_timeout_seconds=30.0,
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "test_client_id",
        "sf/refresh_token": "test_refresh_token",
    })
    transport = FakeSalesforceTransport()
    # Initial token acquisition response
    transport.queue_response(
        status_code=200,
        body=json.dumps({"access_token": "sess_1", "instance_url": "https://test.my.salesforce.com"}).encode("utf-8"),
    )
    clock = ScriptedClock(1000.0)
    sleeper = ScriptedSleeper(clock)
    token_provider = OAuthTokenProvider(settings, store, transport, clock=clock)  # type: ignore[arg-type]
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
        clock=clock,  # type: ignore[arg-type]
        sleeper=sleeper,  # type: ignore[arg-type]
        jitter=NoJitter(),
    )
    return client, transport, clock, sleeper


def test_read_operation_retries_transient_503(test_env) -> None:
    """Verify read operation retries on 503 and succeeds on subsequent attempt."""
    client, transport, clock, sleeper = test_env

    # 1st attempt: 503
    transport.queue_response(status_code=503, body=b"Service Unavailable")
    # 2nd attempt: 200 OK
    transport.queue_response(
        status_code=200,
        body=json.dumps({"Id": "a001", "Title__c": "Engineer"}).encode("utf-8"),
    )

    req = GetRecordRequest(object_name="Job__c", record_id="a00000000000001", fields=["Id", "Title__c"])
    result = client.get_record(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.record_id == "a001"
    # Verify sleep was invoked for backoff
    assert len(sleeper.sleeps) == 1
    assert sleeper.sleeps[0] == 1.0  # initial backoff


def test_uncertain_write_with_replay_safe_false_halts_without_retry(test_env) -> None:
    """Verify mutating upsert with replay_safe=False stops on uncertain timeout without retry."""
    client, transport, clock, sleeper = test_env

    # Queue transport error with uncertain_transmission=True
    transport.queue_error(
        TransportError(
            "Socket timeout after PATCH bytes sent",
            uncertain_transmission=True,
            safe_code="transport_timeout",
        )
    )

    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-001",
        fields={"Title__c": "Staff Engineer"},
        replay_safe=False,  # Replay not safe!
    )
    result = client.upsert_by_external_id(req)

    assert result.is_failure
    assert result.failure is not None
    assert result.failure.remote_outcome == RemoteOutcome.UNKNOWN
    assert result.failure.recovery_action == RecoveryAction.RECONCILE
    # No retry was attempted
    assert len(sleeper.sleeps) == 0


def test_uncertain_write_with_replay_safe_true_retries(test_env) -> None:
    """Verify mutating upsert with replay_safe=True permits bounded retry."""
    client, transport, clock, sleeper = test_env

    # 1st attempt: uncertain timeout
    transport.queue_error(
        TransportError(
            "Socket timeout after PATCH bytes sent",
            uncertain_transmission=True,
            safe_code="transport_timeout",
        )
    )
    # 2nd attempt: 200 OK
    transport.queue_response(
        status_code=200,
        body=json.dumps({"id": "a00000000000001AAA", "success": True}).encode("utf-8"),
    )

    req = UpsertRequest(
        object_name="Job__c",
        external_id_field="External_Id__c",
        external_id_value="ext-001",
        fields={"Title__c": "Staff Engineer"},
        replay_safe=True,  # Caller explicitly guarantees replay safety
    )
    result = client.upsert_by_external_id(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.record_id == "a00000000000001AAA"
    assert len(sleeper.sleeps) == 1


def test_update_record_never_replays_after_uncertain_transmission(test_env) -> None:
    """Verify known-ID update never replays after uncertain transmission."""
    client, transport, clock, sleeper = test_env

    transport.queue_error(
        TransportError(
            "Broken pipe during update",
            uncertain_transmission=True,
            safe_code="connection_broken",
        )
    )

    req = UpdateRequest(
        object_name="Job__c",
        record_id="a00000000000001AAA",
        fields={"Title__c": "Updated Title"},
    )
    result = client.update_record(req)

    assert result.is_failure
    assert result.failure is not None
    assert result.failure.remote_outcome == RemoteOutcome.UNKNOWN
    assert result.failure.recovery_action == RecoveryAction.RECONCILE
    assert len(sleeper.sleeps) == 0


def test_retry_after_longer_than_budget_fails_immediately_without_sleeping(test_env) -> None:
    """Verify 429 with Retry-After exceeding call deadline returns retry_later without sleeping past deadline."""
    client, transport, clock, sleeper = test_env

    # Total call timeout is 30s; server asks for 120s wait
    transport.queue_response(
        status_code=429,
        headers={"retry-after": "120"},
        body=b'{"message": "Rate limit"}',
    )

    req = GetRecordRequest(object_name="Job__c", record_id="a00000000000001", fields=["Id"])
    result = client.get_record(req)

    assert result.is_failure
    assert result.failure is not None
    assert result.failure.http_status == 429
    assert result.failure.recovery_action == RecoveryAction.RETRY_LATER
    # We did NOT sleep 120s
    assert len(sleeper.sleeps) == 0


def test_auth_renewal_on_401_within_call_budget(test_env) -> None:
    """Verify 401 triggers session renewal and subsequent resource retry."""
    client, transport, clock, sleeper = test_env

    # 1st resource attempt: 401 Unauthorized
    transport.queue_response(
        status_code=401,
        body=b'[{"errorCode": "INVALID_SESSION_ID", "message": "Session expired"}]',
    )
    # Renewal token endpoint response:
    transport.queue_response(
        status_code=200,
        body=json.dumps({"access_token": "renewed_token_999", "instance_url": "https://test.my.salesforce.com"}).encode("utf-8"),
    )
    # 2nd resource attempt: 200 OK
    transport.queue_response(
        status_code=200,
        body=json.dumps({"Id": "a001", "Title__c": "Success After Renewal"}).encode("utf-8"),
    )

    req = GetRecordRequest(object_name="Job__c", record_id="a00000000000001", fields=["Id", "Title__c"])
    result = client.get_record(req)

    assert result.is_success
    assert result.value is not None
    assert result.value.fields["Title__c"] == "Success After Renewal"

    # Verify requests sent:
    # 1: Initial token acquisition
    # 2: Resource GET (401)
    # 3: Token renewal POST
    # 4: Resource GET with renewed token (200)
    assert len(transport.requests) == 4
    assert transport.requests[3].headers["authorization"] == "Bearer renewed_token_999"

