"""Domain errors and classification mapping for CONTEXT-01 context construction.

Guarantees:
- Safe diagnostic messages free of sensitive candidate claims or raw job texts.
- Distinct classification into validation, permission, context_budget, missing_configuration,
  and unsupported_input categories.
- Accurate recoverability flags (context_budget is nonrecoverable for unchanged inputs).
"""

from __future__ import annotations

from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory


class ContextError(Exception):
    """Base exception for all context package errors."""

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field_path = field_path
        self.details = details or {}
        self.code = code


class ContextValidationError(ContextError):
    """Raised when request, snapshot, or binding validation fails."""


class ContextPermissionError(ContextError):
    """Raised when an explicitly required item is restricted by candidate permissions."""


class ContextBudgetOverflowError(ContextError):
    """Raised when the complete prompt exceeds the effective model window."""


class ContextConfigurationError(ContextError):
    """Raised when required settings or measurement components are missing."""


class ContextUnsupportedError(ContextError):
    """Raised when an unsupported strategy, purpose, or capability is requested."""


class JobBindingError(ContextError):
    """Raised when job content does not correspond to the declared revision."""


class MeasurementError(ContextError):
    """Raised when token counting or estimation fails."""


class RetrievalError(ContextError):
    """Base exception for retrieval and fusion failures."""


class RetrievalIncompatibleError(RetrievalError):
    """Raised when index embedding space or settings are incompatible with query."""


class RetrievalStaleError(RetrievalError):
    """Raised when index generation or profile version is stale or revoked."""


class RetrievalChannelError(RetrievalError):
    """Raised when an active retrieval channel (keyword or semantic) experiences failure."""


def map_context_exception_to_classified_error(exc: Exception) -> ClassifiedError:
    """Map any context domain exception into a safe ClassifiedError contract."""
    if isinstance(exc, ContextBudgetOverflowError):
        return ClassifiedError.from_category(
            category=ErrorCategory.CONTEXT_BUDGET,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, ContextPermissionError):
        return ClassifiedError.from_category(
            category=ErrorCategory.PERMISSION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, ContextConfigurationError):
        return ClassifiedError.from_category(
            category=ErrorCategory.MISSING_CONFIGURATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, ContextUnsupportedError):
        return ClassifiedError.from_category(
            category=ErrorCategory.UNSUPPORTED_INPUT,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, (ContextValidationError, JobBindingError)):
        return ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, RetrievalIncompatibleError):
        return ClassifiedError.from_category(
            category=ErrorCategory.UNSUPPORTED_INPUT,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, RetrievalStaleError):
        return ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, RetrievalChannelError):
        return ClassifiedError.from_category(
            category=ErrorCategory.MODEL_UNAVAILABLE,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, RetrievalError):
        return ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )
    if isinstance(exc, MeasurementError):
        return ClassifiedError.from_category(
            category=ErrorCategory.MISSING_CONFIGURATION,
            message=exc.message,
            field_path=exc.field_path,
            details=exc.details,
        )

    # Fallback for unexpected exceptions
    return ClassifiedError.from_category(
        category=ErrorCategory.VALIDATION,
        message=f"Context construction failed: {str(exc)}",
    )

