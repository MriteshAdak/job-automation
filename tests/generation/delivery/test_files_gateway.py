"""Unit and wire tests for SalesforceFilesGatewayClient (GEN-06-S03)."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.salesforce import OperationKind, RemoteOutcome
from job_automation.generation.delivery_settings import DeliverySettings
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.file_records import (
    CreateContentDocumentLinkRequest,
    CreateContentVersionRequest,
)
from job_automation.salesforce.files_gateway import SalesforceFilesGatewayClient
from job_automation.salesforce.ports import (
    DefaultClock,
    HttpResponse,
    HttpTransport,
    SalesforceSession,
    TokenProvider,
)
from job_automation.salesforce.transport import TransportError


class FakeHttpTransport(HttpTransport):
    """Controllable transport capturing requests and returning programmed responses."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[HttpResponse | Exception] = []

    def queue_response(self, status_code: int, body: dict[str, Any] | list[Any] | bytes) -> None:
        raw_body = json.dumps(body).encode("utf-8") if isinstance(body, (dict, list)) else body
        self.responses.append(HttpResponse(status_code=status_code, headers={}, body=raw_body))

    def queue_error(self, exc: Exception) -> None:
        self.responses.append(exc)

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.requests.append({
            "method": method,
            "url": url,
            "headers": headers,
            "body": body,
            "timeout": timeout,
        })
        if not self.responses:
            return HttpResponse(status_code=200, headers={}, body=b"{}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeTokenProvider(TokenProvider):
    """Stub token provider returning a static valid session."""

    def __init__(self) -> None:
        self.invalidated_count = 0

    def acquire_session(self, budget: Any) -> tuple[SalesforceSession | None, list[Any], Any]:
        session = SalesforceSession(
            access_token="test_token_123",
            instance_url="https://test.salesforce.com",
            token_type="Bearer",
            issued_at=0.0,
            expires_at=9999999999.0,
        )
        return session, [], None

    def invalidate_session(self) -> None:
        self.invalidated_count += 1


@pytest.fixture
def files_client() -> tuple[SalesforceFilesGatewayClient, FakeHttpTransport]:
    settings = SalesforceSettings(
        instance_url="https://test.salesforce.com",
        client_id_ref="cid",
        credential_ref="cred",
        expected_org_id="00D000000000001EAA",
        api_version="60.0",
        read_timeout_seconds=5.0,
        total_call_timeout_seconds=10.0,
        max_total_sends=3,
    )
    transport = FakeHttpTransport()
    token_provider = FakeTokenProvider()
    delivery_settings = DeliverySettings(
        expected_org_id="00D000000000001EAA",
        max_file_size_bytes=1024 * 1024,
    )
    client = SalesforceFilesGatewayClient(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
        delivery_settings=delivery_settings,
    )
    return client, transport


def test_create_content_version_wire_format(files_client) -> None:
    client, transport = files_client

    # 1. Program 201 Created for ContentVersion POST, then 200 OK for ContentDocumentId lookup
    transport.queue_response(201, {"id": "068000000000001AAA", "success": True})
    transport.queue_response(200, {"ContentDocumentId": "069000000000001AAA"})

    raw_bytes = b"Hello, this is the generated CV text."
    req = CreateContentVersionRequest(
        title="CV_DOCX_Test",
        path_on_client="artifact.docx",
        version_data=raw_bytes,
        reconciliation_marker="gen06:v1:req:art:1",
        content_hash="sha256:" + "c" * 64,
        first_publish_location_id="a01000000000001AAA",
    )

    res = client.create_content_version(req)
    assert res.is_success
    assert res.value is not None
    assert res.value.content_version_id == "068000000000001AAA"
    assert res.value.content_document_id == "069000000000001AAA"

    # Verify wire payload
    assert len(transport.requests) == 2
    create_call = transport.requests[0]
    assert create_call["method"] == "POST"
    assert "sobjects/ContentVersion" in create_call["url"]

    wire_json = json.loads(create_call["body"].decode("utf-8"))
    assert wire_json["Title"] == "CV_DOCX_Test"
    assert wire_json["PathOnClient"] == "artifact.docx"
    assert wire_json["Description"] == "gen06:v1:req:art:1"
    assert wire_json["FirstPublishLocationId"] == "a01000000000001AAA"
    assert base64.b64decode(wire_json["VersionData"]) == raw_bytes


def test_oversized_file_rejected_before_send(files_client) -> None:
    client, transport = files_client
    oversized_bytes = b"X" * (1024 * 1024 + 10)  # > 1 MB ceiling

    req = CreateContentVersionRequest(
        title="Oversized",
        path_on_client="huge.pdf",
        version_data=oversized_bytes,
        reconciliation_marker="gen06:v1:req:art:1",
        content_hash="sha256:" + "d" * 64,
    )
    res = client.create_content_version(req)
    assert res.is_failure
    assert res.failure is not None
    assert res.failure.error.category == ErrorCategory.VALIDATION
    assert len(transport.requests) == 0  # Zero network sends!


def test_storage_limit_exceeded_error_classification(files_client) -> None:
    client, transport = files_client

    # Program Salesforce 400 STORAGE_LIMIT_EXCEEDED
    transport.queue_response(
        400,
        [{"message": "Storage limit exceeded", "errorCode": "STORAGE_LIMIT_EXCEEDED"}],
    )

    req = CreateContentVersionRequest(
        title="CV",
        path_on_client="file.docx",
        version_data=b"test",
        reconciliation_marker="gen06:v1:req:art:1",
        content_hash="sha256:" + "e" * 64,
    )
    res = client.create_content_version(req)
    assert res.is_failure
    assert res.failure is not None
    assert res.failure.error.category == ErrorCategory.CAPACITY
    assert res.failure.safe_provider_code == "STORAGE_LIMIT_EXCEEDED"


def test_rate_limit_exceeded_error_classification(files_client) -> None:
    client, transport = files_client

    transport.queue_response(
        400,
        [{"message": "Daily request limit exceeded", "errorCode": "REQUEST_LIMIT_EXCEEDED"}],
    )

    req = CreateContentVersionRequest(
        title="CV",
        path_on_client="file.docx",
        version_data=b"test",
        reconciliation_marker="gen06:v1:req:art:1",
        content_hash="sha256:" + "f" * 64,
    )
    res = client.create_content_version(req)
    assert res.is_failure
    assert res.failure is not None
    assert res.failure.error.category == ErrorCategory.RATE_LIMIT


def test_uncertain_transmission_on_create_never_blindly_replayed(files_client) -> None:
    client, transport = files_client

    # Transport timeout after sending POST request
    transport.queue_error(
        TransportError("Timeout after transmission", http_status=None, uncertain_transmission=True)
    )

    req = CreateContentVersionRequest(
        title="CV",
        path_on_client="file.docx",
        version_data=b"test",
        reconciliation_marker="gen06:v1:req:art:1",
        content_hash="sha256:" + "a" * 64,
    )
    res = client.create_content_version(req)
    assert res.is_failure
    assert res.failure is not None
    assert res.failure.remote_outcome == RemoteOutcome.UNKNOWN
    assert res.failure.recovery_action.value == "reconcile"
    # Exactly 1 attempt made, never retried blindly!
    assert len(transport.requests) == 1
