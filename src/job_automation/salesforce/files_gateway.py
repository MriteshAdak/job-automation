"""Production implementation of SalesforceFilesGatewayPort (GEN-06-S03)."""

from __future__ import annotations

import json
import urllib.parse
import uuid
from typing import Any, Callable, TypeVar

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.salesforce import (
    AttemptSummary,
    GatewayFailure,
    GatewayResult,
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
)
from job_automation.salesforce.budget import CallBudget
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.diagnostics import create_diagnostic_event
from job_automation.salesforce.files_errors import classify_files_failure
from job_automation.salesforce.files_serialization import (
    build_document_links_soql_query,
    build_marker_soql_query,
    parse_content_document_link_record,
    parse_content_version_record,
    parse_create_response_id,
    serialize_content_document_link_body,
    serialize_content_version_body,
)
from job_automation.salesforce.file_records import (
    ContentDocumentLinkMetadata,
    ContentVersionMetadata,
    CreateContentDocumentLinkRequest,
    CreateContentDocumentLinkResult,
    CreateContentVersionRequest,
    CreateContentVersionResult,
    SalesforceFilesGatewayPort,
)
from job_automation.salesforce.ports import (
    Clock,
    DefaultClock,
    DefaultJitter,
    DefaultSleeper,
    HttpResponse,
    HttpTransport,
    Jitter,
    NoOpDiagnosticsRecorder,
    SafeDiagnosticsRecorder,
    SalesforceSession,
    Sleeper,
    TokenProvider,
)
from job_automation.salesforce.retry import (
    calculate_backoff_delay,
    is_replay_allowed,
)
from job_automation.salesforce.transport import TransportError

T = TypeVar("T")


class SalesforceFilesGatewayClient(SalesforceFilesGatewayPort):
    """Production implementation of SalesforceFilesGatewayPort."""

    def __init__(
        self,
        settings: SalesforceSettings,
        transport: HttpTransport,
        token_provider: TokenProvider,
        delivery_settings: Any = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        jitter: Jitter | None = None,
        recorder: SafeDiagnosticsRecorder | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.token_provider = token_provider
        if delivery_settings is None:
            from job_automation.generation.delivery_settings import DeliverySettings
            self.delivery_settings = DeliverySettings(expected_org_id=settings.expected_org_id or "00D000000000000EAA")
        else:
            self.delivery_settings = delivery_settings
        self.clock: Clock = clock or DefaultClock()
        self.sleeper: Sleeper = sleeper or DefaultSleeper()
        self.jitter: Jitter = jitter or DefaultJitter()
        self.recorder: SafeDiagnosticsRecorder = recorder or NoOpDiagnosticsRecorder()

    @classmethod
    def from_gateway(
        cls,
        gateway: Any,
        delivery_settings: DeliverySettings | None = None,
    ) -> SalesforceFilesGatewayClient:
        """Create Files gateway from existing SalesforceGatewayV2Client instance."""
        return cls(
            settings=gateway.settings,
            transport=gateway.transport,
            token_provider=gateway.token_provider,
            delivery_settings=delivery_settings,
            clock=getattr(gateway, "clock", None),
            sleeper=getattr(gateway, "sleeper", None),
            jitter=getattr(gateway, "jitter", None),
            recorder=getattr(gateway, "recorder", None),
        )

    # -------------------------------------------------------------------------
    # Public Protocol Methods
    # -------------------------------------------------------------------------

    def create_content_version(
        self,
        request: CreateContentVersionRequest,
    ) -> GatewayResult[CreateContentVersionResult]:
        """Upload raw file bytes and marker to create a new ContentVersion."""
        if len(request.version_data) > self.delivery_settings.max_file_size_bytes:
            fail = GatewayFailure(
                error=ClassifiedError.validation(
                    f"File bytes size {len(request.version_data)} exceeds maximum allowed {self.delivery_settings.max_file_size_bytes}"
                ),
                safe_provider_code="file_size_exceeded",
                operation_kind=OperationKind.UPDATE_RECORD,
                remote_outcome=RemoteOutcome.NOT_SENT,
                recovery_action=RecoveryAction.FIX_CONFIGURATION,
            )
            return GatewayResult.fail(fail)

        body = serialize_content_version_body(
            request, marker_field=self.delivery_settings.marker_field
        )
        url = f"{self.settings.instance_url.rstrip('/')}/services/data/{self.settings.api_version}/sobjects/ContentVersion"

        def _parse(session: SalesforceSession, resp: HttpResponse) -> CreateContentVersionResult:
            if resp.status_code != 201:
                raise RuntimeError(f"Unexpected status code {resp.status_code}")
            version_id, err = parse_create_response_id(resp.body)
            if err or not version_id:
                raise RuntimeError(err.message if err else "Missing version id")

            # Resolve ContentDocumentId for the created version
            doc_id = self._resolve_content_document_id(version_id, session)
            return CreateContentVersionResult(
                content_version_id=version_id,
                content_document_id=doc_id,
                reconciliation_marker=request.reconciliation_marker,
            )

        return self._execute_operation(
            call_id=request.call_id,
            operation_name="create_content_version",
            method="POST",
            url=url,
            body=body,
            response_parser=_parse,
            replay_safe=False,
        )

    def get_content_version(
        self,
        version_id: str,
    ) -> GatewayResult[ContentVersionMetadata]:
        """Retrieve metadata for a specific ContentVersion by ID."""
        url = f"{self.settings.instance_url.rstrip('/')}/services/data/{self.settings.api_version}/sobjects/ContentVersion/{version_id}"

        def _parse(session: SalesforceSession, resp: HttpResponse) -> ContentVersionMetadata:
            data = json.loads(resp.body.decode("utf-8"))
            return parse_content_version_record(data, marker_field=self.delivery_settings.marker_field)

        return self._execute_operation(
            call_id=uuid.uuid4(),
            operation_name="get_content_version",
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    def query_content_versions_by_marker(
        self,
        marker: str,
    ) -> GatewayResult[list[ContentVersionMetadata]]:
        """Query ContentVersions across the org by exact reconciliation marker."""
        soql = build_marker_soql_query(
            marker,
            marker_field=self.delivery_settings.marker_field,
            limit=self.delivery_settings.max_query_candidates,
        )
        url = f"{self.settings.instance_url.rstrip('/')}/services/data/{self.settings.api_version}/query?q={urllib.parse.quote(soql)}"

        def _parse(session: SalesforceSession, resp: HttpResponse) -> list[ContentVersionMetadata]:
            data = json.loads(resp.body.decode("utf-8"))
            records = data.get("records", [])
            return [
                parse_content_version_record(r, marker_field=self.delivery_settings.marker_field)
                for r in records
            ]

        return self._execute_operation(
            call_id=uuid.uuid4(),
            operation_name="query_content_versions_by_marker",
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    def create_content_document_link(
        self,
        request: CreateContentDocumentLinkRequest,
    ) -> GatewayResult[CreateContentDocumentLinkResult]:
        """Link a ContentDocument to a Salesforce record (e.g. Generation_Request__c)."""
        body = serialize_content_document_link_body(request)
        url = f"{self.settings.instance_url.rstrip('/')}/services/data/{self.settings.api_version}/sobjects/ContentDocumentLink"

        def _parse(session: SalesforceSession, resp: HttpResponse) -> CreateContentDocumentLinkResult:
            if resp.status_code != 201:
                raise RuntimeError(f"Unexpected status code {resp.status_code}")
            link_id, err = parse_create_response_id(resp.body)
            if err or not link_id:
                raise RuntimeError(err.message if err else "Missing link id")
            return CreateContentDocumentLinkResult(
                link_id=link_id,
                content_document_id=request.content_document_id,
                linked_entity_id=request.linked_entity_id,
                share_type=request.share_type,
                visibility=request.visibility,
            )

        return self._execute_operation(
            call_id=request.call_id,
            operation_name="create_content_document_link",
            method="POST",
            url=url,
            body=body,
            response_parser=_parse,
            replay_safe=False,
        )

    def query_content_document_links(
        self,
        content_document_id: str,
        linked_entity_id: str | None = None,
    ) -> GatewayResult[list[ContentDocumentLinkMetadata]]:
        """Query links for a ContentDocument, optionally filtered by linked entity."""
        soql = build_document_links_soql_query(content_document_id, linked_entity_id)
        url = f"{self.settings.instance_url.rstrip('/')}/services/data/{self.settings.api_version}/query?q={urllib.parse.quote(soql)}"

        def _parse(session: SalesforceSession, resp: HttpResponse) -> list[ContentDocumentLinkMetadata]:
            data = json.loads(resp.body.decode("utf-8"))
            records = data.get("records", [])
            return [parse_content_document_link_record(r) for r in records]

        return self._execute_operation(
            call_id=uuid.uuid4(),
            operation_name="query_content_document_links",
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    def download_content_version_bytes(
        self,
        version_id: str,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> GatewayResult[bytes]:
        """Download exact version bytes for integrity and checksum verification."""
        url = f"{self.settings.instance_url.rstrip('/')}/services/data/{self.settings.api_version}/sobjects/ContentVersion/{version_id}/VersionData"

        def _parse(session: SalesforceSession, resp: HttpResponse) -> bytes:
            if len(resp.body) > max_bytes:
                raise ValueError(f"Downloaded bytes {len(resp.body)} exceeds max allowed {max_bytes}")
            return resp.body

        return self._execute_operation(
            call_id=uuid.uuid4(),
            operation_name="download_content_version_bytes",
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    # -------------------------------------------------------------------------
    # Helper: Resolve ContentDocumentId
    # -------------------------------------------------------------------------

    def _resolve_content_document_id(self, version_id: str, session: SalesforceSession) -> str:
        """Resolve ContentDocumentId for a newly created version."""
        url = f"{self.settings.instance_url.rstrip('/')}/services/data/{self.settings.api_version}/sobjects/ContentVersion/{version_id}"
        headers = {
            "Authorization": f"{session.token_type} {session.access_token}",
            "Accept": "application/json",
            "User-Agent": "job-automation/0.1 (SalesforceGatewayV2; GEN-06)",
        }
        try:
            resp = self.transport.request("GET", url, headers, None, timeout=self.settings.read_timeout_seconds)
            if resp.status_code == 200:
                data = json.loads(resp.body.decode("utf-8"))
                doc_id = data.get("ContentDocumentId")
                if doc_id:
                    return str(doc_id)
        except Exception:
            pass
        return ""

    # -------------------------------------------------------------------------
    # Core Execution Engine
    # -------------------------------------------------------------------------

    def _execute_operation(
        self,
        call_id: uuid.UUID,
        operation_name: str,
        method: str,
        url: str,
        body: bytes | None,
        response_parser: Callable[[SalesforceSession, HttpResponse], T],
        replay_safe: bool,
    ) -> GatewayResult[T]:
        attempts: list[AttemptSummary] = []
        budget = CallBudget(
            clock=self.clock,
            total_timeout_seconds=self.settings.total_call_timeout_seconds,
            max_total_sends=self.settings.max_total_sends,
            max_resource_sends=self.settings.max_resource_sends,
            max_token_sends=self.settings.max_token_sends,
        )

        session, token_attempts, auth_failure = self.token_provider.acquire_session(budget)
        attempts.extend(token_attempts)
        if auth_failure:
            return GatewayResult.fail(auth_failure, attempts=attempts)

        assert session is not None

        attempt_idx = 0
        while True:
            attempt_idx += 1
            if not budget.can_send_resource():
                failure = classify_files_failure(
                    operation=operation_name,
                    status_code=None,
                    body=b"",
                    uncertain_transmission=False,
                    attempts=attempts,
                    exhausted_budget=True,
                )
                return GatewayResult.fail(failure)

            headers = {
                "Authorization": f"{session.token_type} {session.access_token}",
                "Accept": "application/json",
                "User-Agent": "job-automation/0.1 (SalesforceGatewayV2; GEN-06)",
            }
            if body is not None:
                headers["Content-Type"] = "application/json"

            t0 = self.clock.monotonic()
            budget.record_resource_send()
            resp: HttpResponse | None = None
            transport_err: TransportError | None = None

            try:
                resp = self.transport.request(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                    timeout=min(self.settings.read_timeout_seconds, budget.remaining_time()),
                )
            except TransportError as te:
                transport_err = te

            duration_ms = (self.clock.monotonic() - t0) * 1000.0

            if transport_err is not None:
                summary = AttemptSummary(
                    attempt_number=len(attempts) + 1,
                    purpose="resource_request",
                    http_status=transport_err.http_status,
                    duration_ms=duration_ms,
                    safe_code=transport_err.safe_code,
                    uncertain_transmission=transport_err.uncertain_transmission,
                )
                attempts.append(summary)

                # Replay safe check
                if replay_safe and not transport_err.uncertain_transmission and budget.can_send_resource():
                    delay = calculate_backoff_delay(
                        attempt_index=attempt_idx - 1,
                        initial_backoff=self.delivery_settings.initial_backoff_seconds,
                        max_backoff=self.delivery_settings.max_backoff_seconds,
                        jitter=self.jitter,
                    )
                    if delay < budget.remaining_time():
                        self.sleeper.sleep(delay)
                        continue

                failure = classify_files_failure(
                    operation=operation_name,
                    status_code=transport_err.http_status,
                    body=b"",
                    uncertain_transmission=transport_err.uncertain_transmission,
                    attempts=attempts,
                    exhausted_budget=budget.is_exhausted(),
                    override_safe_code=transport_err.safe_code,
                )
                return GatewayResult.fail(failure)

            assert resp is not None
            summary = AttemptSummary(
                attempt_number=len(attempts) + 1,
                purpose="resource_request",
                http_status=resp.status_code,
                duration_ms=duration_ms,
                safe_code=f"http_{resp.status_code}",
                uncertain_transmission=False,
            )
            attempts.append(summary)

            # Check 2xx success
            if 200 <= resp.status_code < 300:
                try:
                    val = response_parser(session, resp)
                    return GatewayResult.success(val, attempts=attempts)
                except Exception as exc:
                    failure = classify_files_failure(
                        operation=operation_name,
                        status_code=resp.status_code,
                        body=resp.body,
                        uncertain_transmission=False,
                        attempts=attempts,
                        override_safe_code="response_parse_error",
                    )
                    return GatewayResult.fail(failure)

            # Handle 401 Session invalidation
            if resp.status_code == 401 and budget.can_send_auth():
                self.token_provider.invalidate_session()
                new_session, new_tok_attempts, new_auth_fail = self.token_provider.acquire_session(budget)
                attempts.extend(new_tok_attempts)
                if new_auth_fail:
                    return GatewayResult.fail(new_auth_fail, attempts=attempts)
                assert new_session is not None
                session = new_session
                continue

            # Classify failure
            failure = classify_files_failure(
                operation=operation_name,
                status_code=resp.status_code,
                body=resp.body,
                uncertain_transmission=False,
                attempts=attempts,
                exhausted_budget=budget.is_exhausted(),
            )
            return GatewayResult.fail(failure)
