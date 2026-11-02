"""Tests for UrllibHttpTransport, TLS validation, and redirect policies (SFCLIENT-01-S02)."""

from __future__ import annotations

import socket
import urllib.error
from unittest.mock import MagicMock, patch
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.transport import (
    TransportError,
    UrllibHttpTransport,
    _NoRedirectHandler,
)


def test_transport_blocks_unapproved_origin() -> None:
    """Verify transport raises PERMISSION error before network call on unapproved origin."""
    settings = SalesforceSettings(
        instance_url="https://legit.my.salesforce.com",
    )
    transport = UrllibHttpTransport(settings)

    with pytest.raises(TransportError) as exc_info:
        transport.request(
            method="GET",
            url="https://evil.attacker.com/steal",
            headers={},
            body=None,
            timeout=5.0,
        )

    err = exc_info.value
    assert err.category == ErrorCategory.PERMISSION
    assert err.safe_code == "origin_not_approved"
    assert not err.uncertain_transmission


def test_redirect_handler_blocks_redirects() -> None:
    """Verify _NoRedirectHandler returns None to block automatic redirection."""
    handler = _NoRedirectHandler()
    res = handler.redirect_request(
        req=MagicMock(),
        fp=MagicMock(),
        code=302,
        msg="Found",
        headers={},
        newurl="https://redirect.example.com",
    )
    assert res is None


def test_transport_enforces_max_response_bytes() -> None:
    """Verify transport rejects oversized responses exceeding max_response_bytes."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
        max_response_bytes=1024,  # 1024 bytes limit
    )
    transport = UrllibHttpTransport(settings)

    # Mock opener returning 200 with 1500 bytes
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.status = 200
    mock_resp.headers = {"Content-Length": "1500"}
    mock_resp.read.return_value = b"x" * 1025

    with patch.object(transport._opener, "open", return_value=mock_resp):
        with pytest.raises(TransportError) as exc_info:
            transport.request(
                method="GET",
                url="https://test.my.salesforce.com/services/data/v60.0/sobjects",
                headers={},
                body=None,
                timeout=5.0,
            )

        err = exc_info.value
        assert err.category == ErrorCategory.CAPACITY
        assert err.safe_code == "response_payload_too_large"


def test_transport_marks_uncertain_transmission_on_mutating_timeouts() -> None:
    """Verify transport flags uncertain_transmission=True when mutating call times out."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
    )
    transport = UrllibHttpTransport(settings)

    # Simulating socket timeout during PATCH
    with patch.object(transport._opener, "open", side_effect=socket.timeout("Read timed out")):
        with pytest.raises(TransportError) as exc_info:
            transport.request(
                method="PATCH",
                url="https://test.my.salesforce.com/services/data/v60.0/sobjects/Job__c/1",
                headers={},
                body=b'{"Title__c": "Test"}',
                timeout=5.0,
            )

        err = exc_info.value
        assert err.category == ErrorCategory.TRANSIENT_NETWORK
        assert err.uncertain_transmission is True
        assert err.safe_code == "transport_timeout"


def test_transport_marks_certain_transmission_on_connect_failure() -> None:
    """Verify transport flags uncertain_transmission=False when DNS or connect fails before sending."""
    settings = SalesforceSettings(
        instance_url="https://test.my.salesforce.com",
    )
    transport = UrllibHttpTransport(settings)

    with patch.object(
        transport._opener,
        "open",
        side_effect=urllib.error.URLError("Name or service not known"),
    ):
        with pytest.raises(TransportError) as exc_info:
            transport.request(
                method="PATCH",
                url="https://test.my.salesforce.com/services/data/v60.0/sobjects/Job__c/1",
                headers={},
                body=b'{"Title__c": "Test"}',
                timeout=5.0,
            )

        err = exc_info.value
        assert err.category == ErrorCategory.TRANSIENT_NETWORK
        assert err.uncertain_transmission is False
        assert err.safe_code == "network_unreachable"
