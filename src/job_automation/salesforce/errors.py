"""Salesforce error classification and failure envelope mapping (SFCLIENT-01-S05).

Enforces:
- Quota precedence: 403 REQUEST_LIMIT_EXCEEDED is classified as rate_limit, NOT permission.
- Allowlisted provider error codes with fixed safe diagnostic messages.
- Never echoing raw Salesforce response messages or credentials.
- Strict recovery action and remote outcome determination based on operation kind and transmission certainty.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.salesforce import (
    AttemptSummary,
    GatewayFailure,
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
)
from job_automation.contracts.primitives import UtcDatetime

# Allowlisted Salesforce REST error codes mapped to categories
KNOWN_SALESFORCE_CODES: dict[str, tuple[ErrorCategory, str, RecoveryAction]] = {
    # Quota / Rate limit
    "REQUEST_LIMIT_EXCEEDED": (
        ErrorCategory.RATE_LIMIT,
        "Daily organization API request limit exceeded.",
        RecoveryAction.RETRY_LATER,
    ),
    "CONCURRENT_REQUEST_LIMIT_EXCEEDED": (
        ErrorCategory.RATE_LIMIT,
        "Concurrent organization request limit reached.",
        RecoveryAction.RETRY_LATER,
    ),
    # Authentication
    "INVALID_SESSION_ID": (
        ErrorCategory.AUTHENTICATION,
        "Salesforce API session is invalid or expired.",
        RecoveryAction.REAUTHORIZE,
    ),
    "SESSION_EXPIRED": (
        ErrorCategory.AUTHENTICATION,
        "Salesforce API session expired.",
        RecoveryAction.REAUTHORIZE,
    ),
    # Permissions
    "INSUFFICIENT_ACCESS_ON_CROSS_REFERENCE_ENTITY": (
        ErrorCategory.PERMISSION,
        "Insufficient object or record permissions in Salesforce org.",
        RecoveryAction.NONE,
    ),
    "INSUFFICIENT_ACCESS_OR_READONLY": (
        ErrorCategory.PERMISSION,
        "Insufficient access or read-only mode for target object/field.",
        RecoveryAction.NONE,
    ),
    "CANNOT_EXECUTE_FLOW_TRIGGER": (
        ErrorCategory.PERMISSION,
        "Flow or trigger execution permission denied.",
        RecoveryAction.NONE,
    ),
    # Capacity
    "STORAGE_LIMIT_EXCEEDED": (
        ErrorCategory.CAPACITY,
        "Salesforce organization data storage limit exceeded.",
        RecoveryAction.NONE,
    ),
    # Validation & Input
    "NOT_FOUND": (
        ErrorCategory.VALIDATION,
        "The requested Salesforce resource or record was not found.",
        RecoveryAction.NONE,
    ),
    "DUPLICATE_VALUE": (
        ErrorCategory.VALIDATION,
        "Duplicate value violates unique External ID constraint.",
        RecoveryAction.NONE,
    ),
    "MULTIPLE_CHOICES": (
        ErrorCategory.VALIDATION,
        "Multiple records match the supplied External ID selector.",
        RecoveryAction.NONE,
    ),
    "INVALID_FIELD": (
        ErrorCategory.VALIDATION,
        "One or more specified fields do not exist or are inaccessible on target object.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
    "MALFORMED_QUERY": (
        ErrorCategory.VALIDATION,
        "SOQL query syntax or field selection is invalid.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
    "REQUIRED_FIELD_MISSING": (
        ErrorCategory.VALIDATION,
        "Required field missing in record payload.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
    "STRING_TOO_LONG": (
        ErrorCategory.VALIDATION,
        "Field value exceeds maximum allowed character length.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
    "INVALID_ID_FIELD": (
        ErrorCategory.VALIDATION,
        "Malformed or invalid Salesforce record ID format.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
}

# OAuth error codes from token endpoint
KNOWN_OAUTH_CODES: dict[str, tuple[ErrorCategory, str, RecoveryAction]] = {
    "invalid_grant": (
        ErrorCategory.AUTHENTICATION,
        "OAuth grant, refresh token, or authorization code is invalid or revoked.",
        RecoveryAction.REAUTHORIZE,
    ),
    "invalid_client": (
        ErrorCategory.AUTHENTICATION,
        "OAuth client ID or client secret is invalid or unapproved.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
    "unauthorized_client": (
        ErrorCategory.PERMISSION,
        "Client application is not authorized for the requested OAuth grant.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
    "invalid_request": (
        ErrorCategory.VALIDATION,
        "OAuth request parameters are missing or malformed.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
    "unsupported_grant_type": (
        ErrorCategory.UNSUPPORTED_INPUT,
        "The specified OAuth grant type is not supported.",
        RecoveryAction.FIX_CONFIGURATION,
    ),
}


def parse_salesforce_error_body(
    body: bytes,
) -> tuple[str | None, str | None]:
    """Parse allowlisted error code and safe message from Salesforce response body."""
    if not body:
        return None, None

    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return None, None

    # Format 1: REST error array: [{"message": "...", "errorCode": "..."}]
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        raw_code = data[0].get("errorCode")
        if raw_code and isinstance(raw_code, str):
            clean_code = raw_code.strip()
            return clean_code, None

    # Format 2: OAuth error object: {"error": "...", "error_description": "..."}
    elif isinstance(data, dict):
        raw_code = data.get("error") or data.get("errorCode")
        if raw_code and isinstance(raw_code, str):
            clean_code = raw_code.strip()
            return clean_code, None

    return None, None


def classify_gateway_failure(
    operation_kind: OperationKind,
    status_code: int | None,
    body: bytes,
    uncertain_transmission: bool,
    attempts: list[AttemptSummary],
    retry_not_before: datetime | None = None,
    exhausted_budget: bool = False,
    override_safe_code: str | None = None,
) -> GatewayFailure:
    """Map operation context, HTTP status, and allowlisted error codes to GatewayFailure."""
    code, _ = parse_salesforce_error_body(body)
    safe_code = override_safe_code or code

    is_mutation = operation_kind in {
        OperationKind.UPSERT_BY_EXTERNAL_ID,
        OperationKind.UPDATE_RECORD,
    }

    # 1. Check known Salesforce REST or OAuth error codes FIRST (Quota before permission!)
    if safe_code and safe_code in KNOWN_SALESFORCE_CODES:
        cat, msg, rec_act = KNOWN_SALESFORCE_CODES[safe_code]
        outcome = RemoteOutcome.REJECTED if not uncertain_transmission else RemoteOutcome.UNKNOWN
        return GatewayFailure(
            error=ClassifiedError.from_category(cat, msg, details={"code": safe_code}),
            safe_provider_code=safe_code,
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=outcome,
            recovery_action=rec_act,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    if safe_code and safe_code in KNOWN_OAUTH_CODES:
        cat, msg, rec_act = KNOWN_OAUTH_CODES[safe_code]
        return GatewayFailure(
            error=ClassifiedError.from_category(cat, msg, details={"code": safe_code}),
            safe_provider_code=safe_code,
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=rec_act,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    # 2. HTTP Status code fallback classification
    if status_code == 401:
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.AUTHENTICATION,
                "Salesforce API request was rejected with 401 Unauthorized.",
                details={"safe_code": "unauthorized_session"},
            ),
            safe_provider_code="unauthorized_session",
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=RemoteOutcome.REJECTED,
            recovery_action=RecoveryAction.REAUTHORIZE,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    elif status_code == 403:
        # Note: If REQUEST_LIMIT_EXCEEDED was in body, it was caught above.
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                "Salesforce API request was rejected with 403 Forbidden.",
                details={"safe_code": "forbidden_access"},
            ),
            safe_provider_code="forbidden_access",
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=RemoteOutcome.REJECTED,
            recovery_action=RecoveryAction.NONE,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    elif status_code == 404:
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                "Salesforce API endpoint or record was not found (404 Not Found).",
                details={"safe_code": "resource_not_found"},
            ),
            safe_provider_code="resource_not_found",
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=RemoteOutcome.REJECTED,
            recovery_action=RecoveryAction.NONE,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    elif status_code == 429:
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.RATE_LIMIT,
                "Salesforce API rate limit exceeded (429 Too Many Requests).",
                details={"safe_code": "rate_limit_exceeded"},
            ),
            safe_provider_code="rate_limit_exceeded",
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=RemoteOutcome.REJECTED,
            recovery_action=RecoveryAction.RETRY_LATER,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    elif status_code == 300:
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                "Multiple records matched the external ID selector (300 Multiple Choices).",
                details={"safe_code": "multiple_external_id_matches"},
            ),
            safe_provider_code="multiple_external_id_matches",
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=RemoteOutcome.REJECTED,
            recovery_action=RecoveryAction.NONE,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    elif status_code is not None and 500 <= status_code <= 599:
        outcome = RemoteOutcome.UNKNOWN if (is_mutation and uncertain_transmission) else RemoteOutcome.REJECTED
        rec_act = RecoveryAction.RECONCILE if (is_mutation and uncertain_transmission) else RecoveryAction.RETRY_LATER
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                f"Salesforce server returned HTTP {status_code} error.",
                details={"safe_code": f"server_error_{status_code}"},
            ),
            safe_provider_code=f"server_error_{status_code}",
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=outcome,
            recovery_action=rec_act,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    # 3. Uncertain network / timeout / disconnect
    if uncertain_transmission and is_mutation:
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_NETWORK,
                "Network timeout or disconnect occurred after mutation request transmission. Remote state is ambiguous.",
                details={"safe_code": safe_code or "uncertain_mutation_transmission"},
            ),
            safe_provider_code=safe_code or "uncertain_mutation_transmission",
            http_status=status_code,
            operation_kind=operation_kind,
            remote_outcome=RemoteOutcome.UNKNOWN,
            recovery_action=RecoveryAction.RECONCILE,
            retry_not_before=retry_not_before,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    # 4. Permanent unmapped 4xx or other failure
    outcome = RemoteOutcome.NOT_SENT if not attempts else RemoteOutcome.REJECTED
    return GatewayFailure(
        error=ClassifiedError.from_category(
            ErrorCategory.UNSUPPORTED_INPUT,
            "Operation could not be completed.",
            details={"safe_code": safe_code or "operation_failed"},
        ),
        safe_provider_code=safe_code or "operation_failed",
        http_status=status_code,
        operation_kind=operation_kind,
        remote_outcome=outcome,
        recovery_action=RecoveryAction.NONE,
        retry_not_before=retry_not_before,
        exhausted_budget=exhausted_budget,
        attempts=attempts,
    )

