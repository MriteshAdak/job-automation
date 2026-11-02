"""Tests for OAuth token lifecycle, session caching, and rotation (SFCLIENT-01-S03)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.salesforce.auth import OAuthTokenProvider
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.credentials import InMemoryCredentialStore
from job_automation.salesforce.ports import DefaultClock
from tests.fakes.salesforce_transport import FakeSalesforceTransport


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.time = start

    def monotonic(self) -> float:
        return self.time

    def advance(self, sec: float) -> None:
        self.time += sec


def test_auth_missing_configuration_reports_prerequisite_failure() -> None:
    """Verify missing client_id_ref or credential_ref returns missing_configuration."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref=None,
        credential_ref=None,
    )
    store = InMemoryCredentialStore()
    transport = FakeSalesforceTransport()
    provider = OAuthTokenProvider(settings, store, transport, clock=DefaultClock())

    session, error = provider.get_session()
    assert session is None
    assert error is not None
    assert error.category == ErrorCategory.MISSING_CONFIGURATION
    assert error.details is not None
    assert error.details.get("prerequisite") == "SF-02"


def test_auth_missing_credential_secret_reports_missing_configuration() -> None:
    """Verify configured references pointing to missing secrets return missing_configuration."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({"sf/client_id": "cid_123"})  # missing refresh_token
    transport = FakeSalesforceTransport()
    provider = OAuthTokenProvider(settings, store, transport, clock=DefaultClock())

    session, error = provider.get_session()
    assert session is None
    assert error is not None
    assert error.category == ErrorCategory.MISSING_CONFIGURATION
    assert "Refresh token credential reference" in error.message


def test_auth_token_acquisition_and_cache_reuse() -> None:
    """Verify successful token exchange caches session and avoids redundant requests."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
        token_url="https://login.salesforce.com/services/oauth2/token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "client_abc",
        "sf/refresh_token": "refresh_xyz",
    })
    transport = FakeSalesforceTransport()
    clock = FakeClock(1000.0)

    # Queue successful OAuth response
    token_response = {
        "access_token": "token_session_001",
        "instance_url": "https://test.my.salesforce.com",
        "token_type": "Bearer",
        "expires_in": 7200,  # 2 hours
    }
    transport.queue_response(
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(token_response).encode("utf-8"),
    )

    provider = OAuthTokenProvider(settings, store, transport, clock=clock)  # type: ignore[arg-type]

    # 1. First get_session triggers network call
    sess1, err1 = provider.get_session()
    assert err1 is None
    assert sess1 is not None
    assert sess1.access_token == "token_session_001"
    assert sess1.instance_url == "https://test.my.salesforce.com"
    assert len(transport.requests) == 1

    # Verify request payload
    req = transport.requests[0]
    assert req.method == "POST"
    assert req.url == "https://login.salesforce.com/services/oauth2/token"
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert b"grant_type=refresh_token" in req.body  # type: ignore[operator]
    assert b"client_id=client_abc" in req.body  # type: ignore[operator]

    # 2. Second get_session within expiry window reuses cached session
    sess2, err2 = provider.get_session()
    assert err2 is None
    assert sess2 == sess1
    assert len(transport.requests) == 1  # No additional network request


def test_auth_token_rotation_saves_new_refresh_token() -> None:
    """Verify that when token endpoint returns a new refresh_token, it updates the store."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "client_abc",
        "sf/refresh_token": "initial_refresh_token",
    })
    transport = FakeSalesforceTransport()
    clock = FakeClock()

    token_response = {
        "access_token": "token_002",
        "instance_url": "https://test.my.salesforce.com",
        "refresh_token": "rotated_replacement_refresh_token",
    }
    transport.queue_response(
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(token_response).encode("utf-8"),
    )

    provider = OAuthTokenProvider(settings, store, transport, clock=clock)  # type: ignore[arg-type]
    sess, err = provider.get_session()
    assert err is None
    assert sess is not None

    # Check store was updated with rotated token
    assert store.get_credential("sf/refresh_token") == "rotated_replacement_refresh_token"
    assert not store.is_exchange_in_progress("sf/refresh_token")


def test_auth_interrupted_rotation_requires_reauthorization() -> None:
    """Verify that pending exchange marker prevents unsafe reuse of single-use refresh token."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "client_abc",
        "sf/refresh_token": "old_token",
    })
    # Simulate interrupted exchange
    store.mark_exchange_in_progress("sf/refresh_token")

    transport = FakeSalesforceTransport()
    provider = OAuthTokenProvider(settings, store, transport, clock=FakeClock())  # type: ignore[arg-type]

    sess, err = provider.get_session()
    assert sess is None
    assert err is not None
    assert err.category == ErrorCategory.AUTHENTICATION
    assert "interrupted" in err.message
    assert len(transport.requests) == 0  # No network call made


def test_auth_invalid_grant_halts_immediately() -> None:
    """Verify invalid_grant OAuth error returns permanent reauthorize action."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "client_abc",
        "sf/refresh_token": "revoked_token",
    })
    transport = FakeSalesforceTransport()
    transport.queue_response(
        status_code=400,
        body=b'{"error": "invalid_grant", "error_description": "authentication failure"}',
    )

    provider = OAuthTokenProvider(settings, store, transport, clock=FakeClock())  # type: ignore[arg-type]
    sess, err = provider.get_session()
    assert sess is None
    assert err is not None
    assert err.category == ErrorCategory.AUTHENTICATION
    assert err.details is not None
    assert err.details.get("safe_code") == "invalid_grant"


def test_auth_rejects_unapproved_instance_origin_in_token_response() -> None:
    """Verify token response returning a rogue instance URL is rejected with PERMISSION error."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        client_id_ref="sf/client_id",
        credential_ref="sf/refresh_token",
    )
    store = InMemoryCredentialStore({
        "sf/client_id": "client_abc",
        "sf/refresh_token": "token_ok",
    })
    transport = FakeSalesforceTransport()
    transport.queue_response(
        status_code=200,
        body=b'{"access_token": "tok", "instance_url": "https://evil.rogue-server.com"}',
    )

    provider = OAuthTokenProvider(settings, store, transport, clock=FakeClock())  # type: ignore[arg-type]
    sess, err = provider.get_session()
    assert sess is None
    assert err is not None
    assert err.category == ErrorCategory.PERMISSION
    assert err.details is not None
    assert err.details.get("safe_code") == "unapproved_token_instance_origin"

