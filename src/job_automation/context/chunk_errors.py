"""Domain errors and classification for CONTEXT-02 evidence chunking.

Guarantees:
- Safe diagnostic messages free of sensitive candidate claims or raw file paths.
- Distinct classification into validation, permission, context_budget, missing_configuration,
  and unsupported_input categories.
- Stable reason codes for invalidation and consumer binding verification.
"""

from __future__ import annotations

from typing import Any

from job_automation.context.errors import (
    ContextBudgetOverflowError,
    ContextConfigurationError,
    ContextError,
    ContextPermissionError,
    ContextUnsupportedError,
    ContextValidationError,
    map_context_exception_to_classified_error,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.profile.errors import (
    InclusionConflictError,
    ProfileApprovalError,
    ProfileConflictError,
    ProfileValidationError,
)


class ChunkError(ContextError):
    """Base exception for all evidence chunking errors."""


class ChunkValidationError(ContextValidationError, ChunkError):
    """Raised when chunk inputs, snapshots, or manifests fail schema or invariant validation."""


class ChunkPermissionError(ContextPermissionError, ChunkError):
    """Raised when an ancestor or required fact is restricted from the target purpose."""


class ChunkCapacityError(ContextBudgetOverflowError, ChunkError):
    """Raised when a rendered chunk exceeds configured size guards (e.g. max_chunk_chars)."""


class ChunkBindingError(ContextValidationError, ChunkError):
    """Raised when consumer binding validation fails against expected profile/purpose."""


class ChunkConfigurationError(ContextConfigurationError, ChunkError):
    """Raised when chunking settings or version configurations are invalid or missing."""


class ChunkUnsupportedError(ContextUnsupportedError, ChunkError):
    """Raised when an unsupported chunking algorithm, granularity, or version is requested."""


def map_chunk_exception_to_classified_error(exc: Exception) -> ClassifiedError:
    """Map any chunking domain exception to a safe ClassifiedError contract.

    Ensures that sensitive candidate claims, secrets, or raw file paths
    do not leak into error messages or details.
    """
    if isinstance(exc, ChunkCapacityError):
        return ClassifiedError.from_category(
            category=ErrorCategory.CONTEXT_BUDGET,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, (ChunkPermissionError, ContextPermissionError, InclusionConflictError)):
        msg = exc.message if hasattr(exc, "message") else str(exc)
        field_path = getattr(exc, "field_path", "allowed_uses")
        details = getattr(exc, "details", {})
        return ClassifiedError.from_category(
            category=ErrorCategory.PERMISSION,
            message=msg,
            field_path=field_path,
            details=details,
        )
    if isinstance(exc, (ChunkConfigurationError, ContextConfigurationError)):
        return ClassifiedError.from_category(
            category=ErrorCategory.MISSING_CONFIGURATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, (ChunkUnsupportedError, ContextUnsupportedError)):
        return ClassifiedError.from_category(
            category=ErrorCategory.UNSUPPORTED_INPUT,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, (ChunkValidationError, ChunkBindingError, ContextValidationError)):
        return ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, (ProfileValidationError, ProfileApprovalError, ProfileConflictError)):
        msg = str(exc)
        field_path = getattr(exc, "field_path", None)
        code = getattr(exc, "code", None)
        details = {"code": code} if code else {}
        return ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=msg,
            field_path=field_path,
            details=details,
        )
    # Generic context exception fallback
    if isinstance(exc, ContextError):
        return map_context_exception_to_classified_error(exc)

    return ClassifiedError.from_category(
        category=ErrorCategory.VALIDATION,
        message=f"Chunk construction failed: {type(exc).__name__}",
        details={"error_type": type(exc).__name__},
    )

