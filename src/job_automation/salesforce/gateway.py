"""Production Salesforce Gateway implementation conforming to SalesforceGatewayV2 (SFCLIENT-01-S04, S05, S06).

Enforces:
- Authenticated, typed reads and explicit mutations.
- Strict caller payload preservation without synthetic domain defaults.
- Bounded monotonic deadlines and send budgets across token renewals and resource requests.
- Conservative write replay prevention: ambiguous mutations are never blindly repeated.
- Safe allowlisted diagnostics with zero secret leaks.
"""

from __future__ import annotations

import copy
import json
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import (
    AttemptSummary,
    ConnectionCheckRequest,
    ConnectionCheckResult,
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
)
from job_automation.salesforce.budget import CallBudget
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.diagnostics import (
    create_diagnostic_event,
)
from job_automation.salesforce.errors import (
    classify_gateway_failure,
    parse_salesforce_error_body,
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
    parse_retry_after,
)
from job_automation.salesforce.serialization import (
    encode_external_id_url,
    parse_describe_response,
    parse_get_record_response,
    parse_limits_response,
    parse_query_response,
    parse_update_response,
    parse_upsert_response,
    serialize_json_body,
    validate_continuation_url,
)
from job_automation.salesforce.transport import TransportError


class SalesforceGatewayV2Client:
    """Production implementation of SalesforceGatewayV2 Protocol."""

    def __init__(
        self,
        settings: SalesforceSettings,
        transport: HttpTransport,
        token_provider: TokenProvider,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        jitter: Jitter | None = None,
        recorder: SafeDiagnosticsRecorder | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.token_provider = token_provider
        self.clock: Clock = clock or DefaultClock()
        self.sleeper: Sleeper = sleeper or DefaultSleeper()
        self.jitter: Jitter = jitter or DefaultJitter()
        self.recorder: SafeDiagnosticsRecorder = recorder or NoOpDiagnosticsRecorder()

    # ===================================================================
    # Public Protocol Methods
    # ===================================================================

    def check_connection(
        self,
        request: ConnectionCheckRequest,
    ) -> GatewayResult[ConnectionCheckResult]:
        """Verify connectivity, identity, and API version with Salesforce org."""
        frozen_req = request.model_copy(deep=True)
        call_id = frozen_req.call_id

        if not frozen_req.perform_network_check:
            # Offline check only
            result = ConnectionCheckResult(
                connected=True,
                org_id=frozen_req.expected_org_id,
                user_id=frozen_req.expected_user_id,
                instance_url=self.settings.instance_url,
                api_version=self.settings.api_version,
                identity_endpoint_verified=False,
            )
            return GatewayResult.success(result)

        # Network verification via userinfo endpoint
        userinfo_url = f"{self.settings.instance_url.rstrip('/')}/services/oauth2/userinfo"

        def _do_check(session: SalesforceSession, resp: HttpResponse) -> ConnectionCheckResult:
            data = json.loads(resp.body.decode("utf-8")) if resp.body else {}
            org_id = data.get("organization_id")
            user_id = data.get("user_id")

            # Verify expected org if configured
            exp_org = frozen_req.expected_org_id or self.settings.expected_org_id
            if exp_org and org_id and exp_org != org_id:
                raise ValueError(
                    f"Connected organization ID '{org_id}' does not match expected '{exp_org}'"
                )

            # Verify expected user if configured
            exp_user = frozen_req.expected_user_id or self.settings.expected_user_id
            if exp_user and user_id and exp_user != user_id:
                raise ValueError(
                    f"Connected user ID '{user_id}' does not match expected '{exp_user}'"
                )

            return ConnectionCheckResult(
                connected=True,
                org_id=org_id,
                user_id=user_id,
                instance_url=session.instance_url,
                api_version=self.settings.api_version,
                identity_endpoint_verified=True,
            )

        return self._execute_operation(
            call_id=call_id,
            operation_kind=OperationKind.CHECK_CONNECTION,
            method="GET",
            url=userinfo_url,
            body=None,
            response_parser=_do_check,
            replay_safe=True,
        )

    def get_limits(
        self,
        request: LimitsRequest,
    ) -> GatewayResult[LimitsResult]:
        """Retrieve organization API limits."""
        frozen_req = request.model_copy(deep=True)
        url = self.settings.build_resource_path("limits/")

        def _parse(session: SalesforceSession, resp: HttpResponse) -> LimitsResult:
            res, err = parse_limits_response(resp.body)
            if err:
                raise RuntimeError(err.message)
            assert res is not None
            return res

        return self._execute_operation(
            call_id=frozen_req.call_id,
            operation_kind=OperationKind.GET_LIMITS,
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    def describe_object(
        self,
        request: DescribeObjectRequest,
    ) -> GatewayResult[DescribeObjectResult]:
        """Retrieve sObject metadata capabilities."""
        frozen_req = request.model_copy(deep=True)
        safe_name = urllib.parse.quote(frozen_req.object_name, safe="")
        url = self.settings.build_resource_path(f"sobjects/{safe_name}/describe")

        def _parse(session: SalesforceSession, resp: HttpResponse) -> DescribeObjectResult:
            res, err = parse_describe_response(frozen_req.object_name, resp.body)
            if err:
                raise RuntimeError(err.message)
            assert res is not None
            return res

        return self._execute_operation(
            call_id=frozen_req.call_id,
            operation_kind=OperationKind.DESCRIBE_OBJECT,
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    def get_record(
        self,
        request: GetRecordRequest,
    ) -> GatewayResult[GetRecordResult]:
        """Retrieve selected fields of a record by ID or External ID."""
        frozen_req = request.model_copy(deep=True)
        fields_param = urllib.parse.quote(",".join(frozen_req.fields))

        if frozen_req.record_id:
            safe_obj = urllib.parse.quote(frozen_req.object_name, safe="")
            safe_id = urllib.parse.quote(frozen_req.record_id, safe="")
            url = self.settings.build_resource_path(f"sobjects/{safe_obj}/{safe_id}?fields={fields_param}")
        else:
            assert frozen_req.external_id_field and frozen_req.external_id_value
            base = self.settings.build_resource_path("")
            ext_url = encode_external_id_url(
                base,
                frozen_req.object_name,
                frozen_req.external_id_field,
                frozen_req.external_id_value,
            )
            url = f"{ext_url}?fields={fields_param}"

        def _parse(session: SalesforceSession, resp: HttpResponse) -> GetRecordResult:
            res, err = parse_get_record_response(frozen_req.object_name, resp.body)
            if err:
                raise RuntimeError(err.message)
            assert res is not None
            return res

        return self._execute_operation(
            call_id=frozen_req.call_id,
            operation_kind=OperationKind.GET_RECORD,
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    def query_page(
        self,
        request: QueryPageRequest,
    ) -> GatewayResult[QueryPageResult]:
        """Execute SOQL query page or fetch next page via continuation."""
        frozen_req = request.model_copy(deep=True)

        if frozen_req.soql:
            encoded_soql = urllib.parse.quote(frozen_req.soql)
            url = self.settings.build_resource_path(f"query/?q={encoded_soql}")
        else:
            assert frozen_req.continuation_token
            # Validate continuation token pinning
            try:
                url = validate_continuation_url(
                    frozen_req.continuation_token,
                    self.settings.instance_url,
                    self.settings.api_version,
                )
            except ValueError as val_err:
                failure = GatewayFailure(
                    error=ClassifiedError.from_category(
                        ErrorCategory.VALIDATION,
                        f"Query continuation token validation failed: {val_err}",
                        details={"safe_code": "invalid_continuation_token"},
                    ),
                    safe_provider_code="invalid_continuation_token",
                    operation_kind=OperationKind.QUERY_PAGE,
                    remote_outcome=RemoteOutcome.NOT_SENT,
                    recovery_action=RecoveryAction.FIX_CONFIGURATION,
                )
                return GatewayResult.fail(failure)

        def _parse(session: SalesforceSession, resp: HttpResponse) -> QueryPageResult:
            res, err = parse_query_response(resp.body)
            if err:
                raise RuntimeError(err.message)
            assert res is not None
            return res

        return self._execute_operation(
            call_id=frozen_req.call_id,
            operation_kind=OperationKind.QUERY_PAGE,
            method="GET",
            url=url,
            body=None,
            response_parser=_parse,
            replay_safe=True,
        )

    def upsert_by_external_id(
        self,
        request: UpsertRequest,
    ) -> GatewayResult[UpsertResult]:
        """Upsert an sObject record by External ID."""
        frozen_req = request.model_copy(deep=True)
        base = self.settings.build_resource_path("")
        url = encode_external_id_url(
            base,
            frozen_req.object_name,
            frozen_req.external_id_field,
            frozen_req.external_id_value,
        )
        body = serialize_json_body(frozen_req.fields)

        def _parse(session: SalesforceSession, resp: HttpResponse) -> UpsertResult:
            ack_at = self.clock.now_utc()
            res, err = parse_upsert_response(
                frozen_req.object_name,
                frozen_req.external_id_field,
                frozen_req.external_id_value,
                resp.status_code,
                resp.body,
                ack_at,
            )
            if err:
                raise RuntimeError(err.message)
            assert res is not None
            return res

        return self._execute_operation(
            call_id=frozen_req.call_id,
            operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
            method="PATCH",
            url=url,
            body=body,
            response_parser=_parse,
            replay_safe=frozen_req.replay_safe,
        )

    def update_record(
        self,
        request: UpdateRequest,
    ) -> GatewayResult[UpdateResult]:
        """Update an sObject record by known Record ID."""
        frozen_req = request.model_copy(deep=True)
        safe_obj = urllib.parse.quote(frozen_req.object_name, safe="")
        safe_id = urllib.parse.quote(frozen_req.record_id, safe="")
        url = self.settings.build_resource_path(f"sobjects/{safe_obj}/{safe_id}")
        body = serialize_json_body(frozen_req.fields)

        def _parse(session: SalesforceSession, resp: HttpResponse) -> UpdateResult:
            ack_at = self.clock.now_utc()
            res, err = parse_update_response(
                frozen_req.object_name,
                frozen_req.record_id,
                resp.status_code,
                ack_at,
            )
            if err:
                raise RuntimeError(err.message)
            assert res is not None
            return res

        # Known-ID updates never permit replay after uncertain transmission
        return self._execute_operation(
            call_id=frozen_req.call_id,
            operation_kind=OperationKind.UPDATE_RECORD,
            method="PATCH",
            url=url,
            body=body,
            response_parser=_parse,
            replay_safe=False,
        )

    # ===================================================================
    # Internal Generic Execution Loop
    # ===================================================================

    def _execute_operation(
        self,
        call_id: Any,
        operation_kind: OperationKind,
        method: str,
        url: str,
        body: bytes | None,
        response_parser: Callable[[SalesforceSession, HttpResponse], Any],
        replay_safe: bool,
    ) -> GatewayResult[Any]:
        """Execute operation within budget, handling 401 renewal, backoff, and safe error classification."""
        budget = CallBudget(
            clock=self.clock,
            total_timeout_seconds=self.settings.total_call_timeout_seconds,
            max_total_sends=self.settings.max_total_sends,
            max_resource_sends=self.settings.max_resource_sends,
            max_token_sends=self.settings.max_token_sends,
        )
        attempts: list[AttemptSummary] = []

        if hasattr(self.token_provider, "reset_call_budget"):
            self.token_provider.reset_call_budget()

        # Initial Session Acquisition
        session, auth_error = self.token_provider.get_session(force_refresh=False)
        if auth_error is not None:
            failure = GatewayFailure(
                error=auth_error,
                safe_provider_code=auth_error.details.get("safe_code") if auth_error.details else None,
                operation_kind=operation_kind,
                remote_outcome=RemoteOutcome.NOT_SENT,
                recovery_action=(
                    RecoveryAction.FIX_CONFIGURATION
                    if auth_error.category == ErrorCategory.MISSING_CONFIGURATION
                    else RecoveryAction.REAUTHORIZE
                ),
                attempts=attempts,
            )
            return GatewayResult.fail(failure)

        assert session is not None

        attempt_idx = 0
        while True:
            attempt_idx += 1
            if not budget.can_send_resource():
                failure = classify_gateway_failure(
                    operation_kind=operation_kind,
                    status_code=None,
                    body=b"",
                    uncertain_transmission=False,
                    attempts=attempts,
                    exhausted_budget=True,
                    override_safe_code="call_budget_exhausted",
                )
                return GatewayResult.fail(failure)

            headers = {
                "Authorization": f"{session.token_type} {session.access_token}",
                "Accept": "application/json",
                "User-Agent": "job-automation/0.1 (SalesforceGatewayV2; SFCLIENT-01)",
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

                self._record_diagnostic(
                    call_id=call_id,
                    operation_kind=operation_kind,
                    attempt_number=summary.attempt_number,
                    purpose="resource_request",
                    http_status=transport_err.http_status,
                    safe_code=transport_err.safe_code,
                    duration_ms=duration_ms,
                    remote_outcome=RemoteOutcome.UNKNOWN if transport_err.uncertain_transmission else RemoteOutcome.NOT_SENT,
                    recovery_action=RecoveryAction.RECONCILE if transport_err.uncertain_transmission else RecoveryAction.NONE,
                )

                # Check if replay is allowed
                if is_replay_allowed(
                    operation_kind=operation_kind,
                    uncertain_transmission=transport_err.uncertain_transmission,
                    replay_safe=replay_safe,
                ) and budget.can_send_resource():
                    delay = calculate_backoff_delay(
                        attempt_index=attempt_idx - 1,
                        initial_backoff=self.settings.initial_backoff_seconds,
                        max_backoff=self.settings.max_backoff_seconds,
                        jitter=self.jitter,
                    )
                    if delay < budget.remaining_time():
                        self.sleeper.sleep(delay)
                        continue

                # Not replayable or budget exhausted
                failure = classify_gateway_failure(
                    operation_kind=operation_kind,
                    status_code=transport_err.http_status,
                    body=b"",
                    uncertain_transmission=transport_err.uncertain_transmission,
                    attempts=attempts,
                    exhausted_budget=budget.is_exhausted(),
                    override_safe_code=transport_err.safe_code,
                )
                return GatewayResult.fail(failure)

            assert resp is not None
            code, _ = parse_salesforce_error_body(resp.body)

            summary = AttemptSummary(
                attempt_number=len(attempts) + 1,
                purpose="resource_request",
                http_status=resp.status_code,
                duration_ms=duration_ms,
                safe_code=code,
                uncertain_transmission=resp.uncertain_transmission,
            )
            attempts.append(summary)

            self._record_diagnostic(
                call_id=call_id,
                operation_kind=operation_kind,
                attempt_number=summary.attempt_number,
                purpose="resource_request",
                http_status=resp.status_code,
                safe_code=code,
                duration_ms=duration_ms,
                remote_outcome=RemoteOutcome.ACKNOWLEDGED if 200 <= resp.status_code < 300 else RemoteOutcome.REJECTED,
                recovery_action=RecoveryAction.NONE if 200 <= resp.status_code < 300 else RecoveryAction.NONE,
            )

            # Case A: Success (2xx)
            if 200 <= resp.status_code < 300:
                try:
                    result_val = response_parser(session, resp)
                    return GatewayResult.success(result_val, attempts=attempts)
                except Exception as parse_exc:
                    failure = GatewayFailure(
                        error=ClassifiedError.from_category(
                            ErrorCategory.TRANSIENT_SERVICE,
                            f"Protocol error parsing successful response: {parse_exc}",
                            details={"safe_code": "protocol_parsing_error"},
                        ),
                        safe_provider_code="protocol_parsing_error",
                        http_status=resp.status_code,
                        operation_kind=operation_kind,
                        remote_outcome=RemoteOutcome.UNKNOWN if operation_kind in {OperationKind.UPSERT_BY_EXTERNAL_ID, OperationKind.UPDATE_RECORD} else RemoteOutcome.REJECTED,
                        recovery_action=RecoveryAction.RECONCILE if operation_kind in {OperationKind.UPSERT_BY_EXTERNAL_ID, OperationKind.UPDATE_RECORD} else RecoveryAction.NONE,
                        attempts=attempts,
                    )
                    return GatewayResult.fail(failure)

            # Case B: 401 Unauthorized / INVALID_SESSION_ID -> One renewal attempt allowed
            if resp.status_code == 401 or code == "INVALID_SESSION_ID":
                if budget.can_send_token():
                    if hasattr(self.token_provider, "invalidate_session"):
                        self.token_provider.invalidate_session()
                    renewed_session, renew_err = self.token_provider.get_session(force_refresh=True)
                    if renewed_session is not None:
                        session = renewed_session
                        continue  # Retry resource request with new token
                failure = classify_gateway_failure(
                    operation_kind=operation_kind,
                    status_code=resp.status_code,
                    body=resp.body,
                    uncertain_transmission=False,
                    attempts=attempts,
                    exhausted_budget=budget.is_exhausted(),
                )
                return GatewayResult.fail(failure)

            # Case C: 429 Rate Limit
            if resp.status_code == 429:
                retry_after_hdr = resp.headers.get("retry-after")
                retry_after_sec = parse_retry_after(retry_after_hdr, self.clock)
                if (
                    is_replay_allowed(operation_kind, uncertain_transmission=False, replay_safe=replay_safe)
                    and budget.can_send_resource()
                ):
                    backoff = calculate_backoff_delay(
                        attempt_index=attempt_idx - 1,
                        initial_backoff=self.settings.initial_backoff_seconds,
                        max_backoff=self.settings.max_backoff_seconds,
                        jitter=self.jitter,
                    )
                    effective_delay = max(retry_after_sec or 0.0, backoff)
                    if effective_delay < budget.remaining_time():
                        self.sleeper.sleep(effective_delay)
                        continue
                failure = classify_gateway_failure(
                    operation_kind=operation_kind,
                    status_code=resp.status_code,
                    body=resp.body,
                    uncertain_transmission=False,
                    attempts=attempts,
                    exhausted_budget=budget.is_exhausted(),
                )
                return GatewayResult.fail(failure)

            # Case D: 5xx Transient Service Error
            if 500 <= resp.status_code <= 599:
                if (
                    is_replay_allowed(
                        operation_kind=operation_kind,
                        uncertain_transmission=False,
                        replay_safe=replay_safe,
                    )
                    and budget.can_send_resource()
                ):
                    delay = calculate_backoff_delay(
                        attempt_index=attempt_idx - 1,
                        initial_backoff=self.settings.initial_backoff_seconds,
                        max_backoff=self.settings.max_backoff_seconds,
                        jitter=self.jitter,
                    )
                    if delay < budget.remaining_time():
                        self.sleeper.sleep(delay)
                        continue
                failure = classify_gateway_failure(
                    operation_kind=operation_kind,
                    status_code=resp.status_code,
                    body=resp.body,
                    uncertain_transmission=False,
                    attempts=attempts,
                    exhausted_budget=budget.is_exhausted(),
                )
                return GatewayResult.fail(failure)

            # Case E: Terminal Failure (403 quota or permission, 404, 300, 400 validation, etc.)
            failure = classify_gateway_failure(
                operation_kind=operation_kind,
                status_code=resp.status_code,
                body=resp.body,
                uncertain_transmission=False,
                attempts=attempts,
                exhausted_budget=budget.is_exhausted(),
            )
            return GatewayResult.fail(failure)

    def _record_diagnostic(
        self,
        call_id: Any,
        operation_kind: OperationKind,
        attempt_number: int,
        purpose: str,
        http_status: int | None,
        safe_code: str | None,
        duration_ms: float,
        remote_outcome: RemoteOutcome,
        recovery_action: RecoveryAction,
    ) -> None:
        """Safely record allowlisted diagnostic event without leaking sensitive parameters."""
        try:
            evt = create_diagnostic_event(
                call_id=str(call_id),
                operation_kind=operation_kind.value,
                api_version=self.settings.api_version,
                attempt_number=attempt_number,
                purpose=purpose,
                http_status=http_status,
                safe_code=safe_code,
                duration_ms=duration_ms,
                remote_outcome=remote_outcome.value,
                recovery_action=recovery_action.value,
                utc_timestamp=self.clock.now_utc(),
            )
            self.recorder.record_event(evt)
        except Exception:
            pass

