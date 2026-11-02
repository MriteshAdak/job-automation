"""Error classification for Salesforce Files operations (GEN-06-S03)."""

from __future__ import annotations

import json
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.salesforce import (
    AttemptSummary,
    GatewayFailure,
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
)
from job_automation.salesforce.errors import (
    KNOWN_SALESFORCE_CODES,
    parse_salesforce_error_body,
)


def classify_files_failure(
    operation: str,
    status_code: int | None,
    body: bytes,
    uncertain_transmission: bool,
    attempts: list[AttemptSummary],
    exhausted_budget: bool = False,
    override_safe_code: str | None = None,
) -> GatewayFailure:
    """Classify failure from a Salesforce Files operation with safe diagnostics and capacity/quota awareness."""
    is_mutation = operation in ("create_content_version", "create_content_document_link")
    op_kind = OperationKind.UPDATE_RECORD if is_mutation else OperationKind.GET_RECORD

    # Uncertain transmission on mutation means outcome is UNKNOWN and needs reconciliation
    if uncertain_transmission:
        return GatewayFailure(
            error=ClassifiedError.transient_network(
                f"Salesforce Files operation '{operation}' transmission was uncertain"
            ),
            safe_provider_code=override_safe_code or "uncertain_network_transmission",
            http_status=status_code,
            operation_kind=op_kind,
            remote_outcome=RemoteOutcome.UNKNOWN if is_mutation else RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.RECONCILE if is_mutation else RecoveryAction.RETRY_LATER,
            exhausted_budget=exhausted_budget,
            attempts=attempts,
        )

    if exhausted_budget:
        return GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.RATE_LIMIT,
                f"Call budget exhausted during Files operation '{operation}'",
            ),
            safe_provider_code="call_budget_exhausted",
            http_status=status_code,
            operation_kind=op_kind,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.RETRY_LATER,
            exhausted_budget=True,
            attempts=attempts,
        )

    code, raw_msg = parse_salesforce_error_body(body)
    code = override_safe_code or code

    # Classify by HTTP status code or known provider error code
    if code in KNOWN_SALESFORCE_CODES:
        cat, safe_msg, rec = KNOWN_SALESFORCE_CODES[code]
    elif status_code == 401:
        cat = ErrorCategory.AUTHENTICATION
        safe_msg = "Salesforce authentication required or session expired."
        rec = RecoveryAction.REAUTHORIZE
    elif status_code == 403:
        cat = ErrorCategory.PERMISSION
        safe_msg = "Access denied for Salesforce Files operation."
        rec = RecoveryAction.FIX_CONFIGURATION
    elif status_code == 429:
        cat = ErrorCategory.RATE_LIMIT
        safe_msg = "Salesforce request rate limit exceeded."
        rec = RecoveryAction.RETRY_LATER
    elif status_code and 500 <= status_code < 600:
        cat = ErrorCategory.TRANSIENT_NETWORK
        safe_msg = f"Salesforce server returned HTTP {status_code}."
        rec = RecoveryAction.RETRY_LATER
    else:
        cat = ErrorCategory.VALIDATION
        safe_msg = f"Salesforce Files operation '{operation}' failed with status {status_code}."
        rec = RecoveryAction.NONE

    # Special check for storage limit in message
    if "STORAGE_LIMIT_EXCEEDED" in (raw_msg or "") or "storage limit" in (raw_msg or "").lower():
        cat = ErrorCategory.CAPACITY
        safe_msg = "Salesforce storage limit exceeded."
        code = "STORAGE_LIMIT_EXCEEDED"
        rec = RecoveryAction.FIX_CONFIGURATION

    # Outcome
    if status_code is not None and 400 <= status_code < 500:
        outcome = RemoteOutcome.REJECTED
    elif status_code is not None and status_code >= 500:
        outcome = RemoteOutcome.UNKNOWN if is_mutation else RemoteOutcome.NOT_SENT
    else:
        outcome = RemoteOutcome.NOT_SENT

    return GatewayFailure(
        error=ClassifiedError.from_category(cat, safe_msg),
        safe_provider_code=code,
        http_status=status_code,
        operation_kind=op_kind,
        remote_outcome=outcome,
        recovery_action=rec,
        exhausted_budget=exhausted_budget,
        attempts=attempts,
    )

