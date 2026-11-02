"""Specialized error classifications and reason codes for GEN-02 input operations."""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory


class GEN02Error(Exception):
    """Base exception for GEN-02 errors."""

    def __init__(self, message: str, reason_code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.reason_code = reason_code
        self.details = details or {}

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.VALIDATION) -> ClassifiedError:
        d = dict(self.details)
        d["reason_code"] = self.reason_code
        return ClassifiedError.from_category(category, self.message, details=d)


def job_unavailable_error(
    canonical_job_id: uuid.UUID | str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when target job is unavailable and candidate override was not granted."""
    d = dict(details or {})
    d["reason_code"] = "job_unavailable"
    d["canonical_job_id"] = str(canonical_job_id)
    msg = message or f"Job {canonical_job_id} is confirmed unavailable and allow_unavailable_job override was not granted"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )


def freeze_conflict_error(
    request_id: uuid.UUID | str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when request is already sealed with different options or inputs."""
    d = dict(details or {})
    d["reason_code"] = "freeze_conflict"
    d["request_id"] = str(request_id)
    msg = message or f"Request {request_id} is already frozen with different options or inputs"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )


def profile_unapproved_error(
    candidate_id: uuid.UUID | str | None = None,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when candidate profile has no approved published snapshot."""
    d = dict(details or {})
    d["reason_code"] = "profile_unapproved"
    if candidate_id:
        d["candidate_id"] = str(candidate_id)
    msg = message or "No approved candidate profile snapshot found for generation"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )


def job_snapshot_mismatch_error(
    canonical_job_id: uuid.UUID | str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when job revision or normalized posting content hash fails consistency check."""
    d = dict(details or {})
    d["reason_code"] = "job_snapshot_mismatch"
    d["canonical_job_id"] = str(canonical_job_id)
    msg = message or f"Job content or revision hash mismatch for canonical job {canonical_job_id}"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )


def frozen_input_missing_error(
    item_id: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when an expected frozen snapshot, seal, or recipe is missing in storage."""
    d = dict(details or {})
    d["reason_code"] = "frozen_input_missing"
    d["item_id"] = item_id
    msg = message or f"Frozen input '{item_id}' not found in durable storage"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )


def frozen_input_corrupt_error(
    item_id: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when a stored seal or snapshot fails checksum validation."""
    d = dict(details or {})
    d["reason_code"] = "frozen_input_corrupt"
    d["item_id"] = item_id
    msg = message or f"Stored frozen input '{item_id}' failed checksum verification"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )


def frozen_index_mismatch_error(
    candidate_id: uuid.UUID | str,
    purpose: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when no compatible RAG index generation exists or index verification fails."""
    d = dict(details or {})
    d["reason_code"] = "frozen_index_mismatch"
    d["candidate_id"] = str(candidate_id)
    d["purpose"] = purpose
    msg = message or f"No compatible index generation found for candidate {candidate_id} and purpose {purpose}"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )


def recipe_unavailable_error(
    recipe_id: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when required context recipe or model configuration is missing."""
    d = dict(details or {})
    d["reason_code"] = "recipe_unavailable"
    d["recipe_id"] = recipe_id
    msg = message or f"Context recipe '{recipe_id}' is unavailable"
    return ClassifiedError.from_category(
        ErrorCategory.MISSING_CONFIGURATION,
        msg,
        details=d,
    )


def preflight_interrupted_error(
    request_id: uuid.UUID | str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ClassifiedError:
    """Return classified error when a preflight attempt was interrupted."""
    d = dict(details or {})
    d["reason_code"] = "preflight_interrupted"
    d["request_id"] = str(request_id)
    msg = message or f"Preflight attempt for request {request_id} was interrupted"
    return ClassifiedError.from_category(
        ErrorCategory.VALIDATION,
        msg,
        details=d,
    )

