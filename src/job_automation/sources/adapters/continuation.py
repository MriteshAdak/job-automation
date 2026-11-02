"""Continuation token creation, validation, and cycle detection (SOURCE-02-S02).

Validates continuation tokens against bound source, scope, adapter, input hash,
and options hash.
"""

from __future__ import annotations

from job_automation.contracts.adapter_results import Continuation
from job_automation.contracts.errors import ErrorCategory, ValidationIssue


def create_continuation(
    kind: str,
    value: str,
    source_key: str,
    scope_id: str,
    adapter_name: str,
    input_hash: str | None = None,
    options_hash: str | None = None,
) -> Continuation:
    """Create a typed, validated Continuation instance."""
    return Continuation(
        kind=kind,
        value=value,
        source_key=source_key,
        scope_id=scope_id,
        adapter_name=adapter_name,
        input_hash=input_hash,
        options_hash=options_hash,
    )


def validate_continuation(
    token: Continuation,
    expected_source_key: str,
    expected_scope_id: str,
    expected_adapter_name: str,
    expected_input_hash: str | None = None,
    expected_options_hash: str | None = None,
    prior_token: Continuation | None = None,
) -> list[ValidationIssue]:
    """Validate that a continuation token is compatible with the current execution context.

    Returns:
        List of ValidationIssue items (empty if valid).
    """
    issues: list[ValidationIssue] = []

    if token.source_key != expected_source_key:
        issues.append(
            ValidationIssue(
                field_path="source_key",
                code="continuation_source_mismatch",
                message=f"Continuation source key '{token.source_key}' does not match expected '{expected_source_key}'",
            )
        )

    if token.scope_id != expected_scope_id:
        issues.append(
            ValidationIssue(
                field_path="scope_id",
                code="continuation_scope_mismatch",
                message=f"Continuation scope '{token.scope_id}' does not match expected '{expected_scope_id}'",
            )
        )

    if token.adapter_name != expected_adapter_name:
        issues.append(
            ValidationIssue(
                field_path="adapter_name",
                code="continuation_adapter_mismatch",
                message=f"Continuation adapter '{token.adapter_name}' does not match expected '{expected_adapter_name}'",
            )
        )

    if expected_input_hash is not None and token.input_hash is not None:
        if token.input_hash != expected_input_hash:
            issues.append(
                ValidationIssue(
                    field_path="input_hash",
                    code="continuation_input_stale",
                    message="Continuation input hash does not match current input bytes; input has changed",
                )
            )

    if expected_options_hash is not None and token.options_hash is not None:
        if token.options_hash != expected_options_hash:
            issues.append(
                ValidationIssue(
                    field_path="options_hash",
                    code="continuation_options_mismatch",
                    message="Continuation options hash does not match current parsing/paging options",
                )
            )

    # Detect immediate non-progress (repeating the exact same token value without advancing)
    if prior_token is not None and prior_token.value == token.value:
        issues.append(
            ValidationIssue(
                field_path="value",
                code="continuation_non_progress_loop",
                message=f"Immediate non-progress detected: token value '{token.value}' repeated",
            )
        )

    return issues
