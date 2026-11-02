"""Domain errors and classification for CONTEXT-03 local vector and keyword indexing.

Guarantees:
- Safe diagnostic messages free of sensitive candidate claims or raw file paths.
- Distinct classification into validation, unsupported_input, context_budget/capacity,
  missing_configuration, permission, and transient_service categories.
- Stable reason codes for compatibility failures, stale bindings, and data corruption.
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


class IndexError(ContextError):
    """Base exception for all local index errors."""


class IndexValidationError(ContextValidationError, IndexError):
    """Raised when index inputs, chunks, or manifests fail validation invariants."""


class IndexIncompatibleError(ContextUnsupportedError, IndexError):
    """Raised when models, dimensions, vector dtypes, or versions are incompatible."""


class IndexBindingError(ContextValidationError, IndexError):
    """Raised when candidate, profile, or purpose binding fails against expected state."""


class IndexStaleError(ContextValidationError, IndexError):
    """Raised when an index is outdated relative to current profile or activation state."""


class IndexPermissionError(ContextPermissionError, IndexError):
    """Raised when unauthorized facts or restricted purposes are encountered."""


class IndexCapacityError(ContextBudgetOverflowError, IndexError):
    """Raised when chunks, vectors, text, or memory limits exceed configured capacity."""


class IndexConfigurationError(ContextConfigurationError, IndexError):
    """Raised when index or embedding settings are missing, contradictory, or invalid."""


class IndexStorageError(IndexError):
    """Raised when database or filesystem operations fail during index persistence."""

    def __init__(
        self,
        message: str,
        operation: str = "storage",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.operation = operation
        self.details = details or {}


class IndexCorruptionError(IndexError):
    """Raised when an on-disk index payload fails checksum or structural verification."""

    def __init__(
        self,
        message: str,
        artifact: str = "payload",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.artifact = artifact
        self.details = details or {}


def map_index_exception_to_classified_error(exc: Exception) -> ClassifiedError:
    """Map any index domain exception to a safe ClassifiedError contract.

    Ensures that sensitive candidate claims, raw prompt text, or secret paths
    do not leak into error messages or details.
    """
    if isinstance(exc, IndexCapacityError):
        return ClassifiedError.from_category(
            category=ErrorCategory.CAPACITY,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, IndexIncompatibleError):
        return ClassifiedError.from_category(
            category=ErrorCategory.UNSUPPORTED_INPUT,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, IndexConfigurationError):
        return ClassifiedError.from_category(
            category=ErrorCategory.MISSING_CONFIGURATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, IndexPermissionError):
        return ClassifiedError.from_category(
            category=ErrorCategory.PERMISSION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, (IndexValidationError, IndexBindingError, IndexStaleError)):
        return ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, IndexCorruptionError):
        return ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=exc.message,
            field_path=exc.artifact,
            details={"reason": "corruption_detected", **exc.details},
        )
    if isinstance(exc, IndexStorageError):
        return ClassifiedError.from_category(
            category=ErrorCategory.TRANSIENT_SERVICE,
            message=exc.message,
            field_path=exc.operation,
            details={"reason": "storage_io_error", **exc.details},
        )
    if isinstance(exc, ContextError):
        return map_context_exception_to_classified_error(exc)

    return ClassifiedError.from_category(
        category=ErrorCategory.VALIDATION,
        message=f"Index operation failed: {type(exc).__name__}",
        details={"error_type": type(exc).__name__},
    )

