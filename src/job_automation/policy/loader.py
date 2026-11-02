"""Safe local policy configuration loader for C02 SearchPolicy."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from job_automation.contracts.errors import (
    ClassifiedError,
    ErrorCategory,
    ValidationIssue,
)
from job_automation.policy.models import POLICY_SCHEMA_VERSION


def _parse_pairs_rejecting_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Parse JSON key-value pairs, raising ValueError on duplicate keys."""
    res: dict[str, Any] = {}
    for k, v in pairs:
        if k in res:
            raise ValueError(f"Duplicate JSON object key: '{k}'")
        res[k] = v
    return res


def _reject_non_finite_floats(val: str) -> None:
    """Callback to reject NaN, Infinity, -Infinity literals."""
    raise ValueError(f"Non-finite numeric literal forbidden: '{val}'")


def load_policy_dict(
    policy_path: str | Path,
) -> tuple[dict[str, Any] | None, dict[str, bool], list[ValidationIssue], ClassifiedError | None]:
    """Safely read and parse a JSON policy file into a dictionary.

    Returns:
        (parsed_dict, explicit_on_missing_map, validation_issues, classified_error)
        - parsed_dict: Dict of policy content if loaded without blocking structural error, else None.
        - explicit_on_missing_map: Maps criterion_id -> bool indicating if on_missing was explicitly in JSON.
        - validation_issues: Structural issues detected during load.
        - classified_error: Fatal loading error (e.g. file missing, permission, or unparseable JSON).
    """
    path = Path(policy_path)
    issues: list[ValidationIssue] = []
    explicit_on_missing: dict[str, bool] = {}

    if not path.is_file():
        err = ClassifiedError.from_category(
            category=ErrorCategory.MISSING_CONFIGURATION,
            message=f"Search policy file not found: {path.name}",
            field_path=str(path),
        )
        issues.append(
            ValidationIssue(
                field_path="policy_path",
                code="missing_policy_file",
                message=f"Policy file does not exist: {path.name}",
                severity="error",
            )
        )
        return None, explicit_on_missing, issues, err

    try:
        raw_bytes = path.read_bytes()
    except PermissionError as exc:
        err = ClassifiedError.from_category(
            category=ErrorCategory.PERMISSION,
            message=f"Permission denied accessing policy file: {path.name}",
            field_path=str(path),
        )
        issues.append(
            ValidationIssue(
                field_path="policy_path",
                code="permission_denied",
                message=f"Permission denied reading policy file: {path.name}",
                severity="error",
            )
        )
        return None, explicit_on_missing, issues, err
    except OSError as exc:
        err = ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=f"I/O error reading policy file: {path.name}",
            field_path=str(path),
        )
        issues.append(
            ValidationIssue(
                field_path="policy_path",
                code="io_error",
                message=f"I/O error reading policy file: {path.name}",
                severity="error",
            )
        )
        return None, explicit_on_missing, issues, err

    # Decode UTF-8 handling optional UTF-8 BOM
    try:
        # utf-8-sig strips BOM if present, otherwise decodes plain utf-8
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        err = ClassifiedError.from_category(
            category=ErrorCategory.UNSUPPORTED_INPUT,
            message=f"Policy file is not valid UTF-8: {path.name}",
            field_path=str(path),
        )
        issues.append(
            ValidationIssue(
                field_path="policy_path",
                code="invalid_encoding",
                message="Policy file must be encoded in UTF-8 (with or without BOM)",
                severity="error",
            )
        )
        return None, explicit_on_missing, issues, err

    # Parse JSON with duplicate key detection
    try:
        raw_data = json.loads(
            text,
            object_pairs_hook=_parse_pairs_rejecting_duplicates,
            parse_constant=_reject_non_finite_floats,
        )
    except ValueError as exc:
        safe_msg = str(exc)
        if "SECRET" in safe_msg:
            safe_msg = "Malformed JSON syntax or invalid literal"
        err = ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=f"Failed to parse JSON policy: {safe_msg}",
            field_path=str(path),
        )
        code = "duplicate_json_key" if "Duplicate JSON object key" in str(exc) else "malformed_json"
        issues.append(
            ValidationIssue(
                field_path="policy",
                code=code,
                message=safe_msg,
                severity="error",
            )
        )
        return None, explicit_on_missing, issues, err

    if not isinstance(raw_data, dict):
        err = ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message="Policy root must be a JSON object",
            field_path=str(path),
        )
        issues.append(
            ValidationIssue(
                field_path="policy",
                code="invalid_root_type",
                message="Policy root must be a JSON object, not an array or primitive",
                severity="error",
            )
        )
        return None, explicit_on_missing, issues, err

    # Check schema_version
    schema_ver = raw_data.get("schema_version")
    if schema_ver != POLICY_SCHEMA_VERSION:
        err = ClassifiedError.from_category(
            category=ErrorCategory.UNSUPPORTED_INPUT,
            message=(
                f"Unsupported policy schema_version '{schema_ver}'; "
                f"expected '{POLICY_SCHEMA_VERSION}'"
            ),
            field_path="schema_version",
        )
        issues.append(
            ValidationIssue(
                field_path="schema_version",
                code="unsupported_schema_version",
                message=(
                    f"Unsupported policy schema_version '{schema_ver}'; "
                    f"only version '{POLICY_SCHEMA_VERSION}' is supported"
                ),
                severity="error",
            )
        )
        return None, explicit_on_missing, issues, err

    # Track explicit on_missing in hard_criteria
    hard_crit_raw = raw_data.get("hard_criteria")
    if isinstance(hard_crit_raw, list):
        for idx, crit in enumerate(hard_crit_raw):
            if isinstance(crit, dict):
                crit_id = crit.get("criterion_id") or f"index_{idx}"
                explicit_on_missing[crit_id] = "on_missing" in crit

    return raw_data, explicit_on_missing, issues, None

