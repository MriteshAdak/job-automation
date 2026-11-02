"""Standard error codes and validation issue helpers for SOURCE-01."""

from __future__ import annotations

from job_automation.contracts.errors import ValidationIssue

ERR_MISSING_REGISTRY = "missing_registry"
ERR_MALFORMED_REGISTRY = "malformed_registry"
ERR_DUPLICATE_KEY = "duplicate_source_key"
ERR_DUPLICATE_JSON_MEMBER = "duplicate_json_member"
ERR_UNSUPPORTED_VERSION = "unsupported_schema_version"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INVALID_ENDPOINT = "invalid_endpoint"
ERR_DISALLOWED_CREDENTIAL = "disallowed_credential"
ERR_INVALID_REQUEST_POLICY = "invalid_request_policy"
ERR_CONFLICTING_POLICY = "conflicting_request_policy"
ERR_ACCESS_UNREVIEWED = "access_unreviewed"
ERR_ACCESS_DENIED = "access_denied"
ERR_ACCESS_EXPIRED = "access_expired"
ERR_ACCESS_METHOD_MISMATCH = "access_method_mismatch"
ERR_ATTRIBUTION_UNKNOWN = "attribution_unknown"
ERR_ATTRIBUTION_MISSING_NOTICE = "attribution_missing_notice"
ERR_SCOPE_CONTRADICTION = "scope_contradiction"
ERR_SOURCE_DISABLED = "source_disabled"
ERR_SOURCE_NOT_CONFIGURED = "source_not_configured"
ERR_DUPLICATE_SELECTION = "duplicate_selection"


def make_issue(
    code: str,
    message: str,
    field_path: str = "",
    severity: str = "error",
) -> ValidationIssue:
    """Create a standardized ValidationIssue."""
    return ValidationIssue(
        field_path=field_path,
        code=code,
        message=message,
        severity=severity,
    )
