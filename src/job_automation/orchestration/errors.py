"""Errors and exceptions for pipeline orchestration and recovery (RUN-01)."""

from __future__ import annotations

from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory


class OrchestrationError(Exception):
    """Base class for all orchestration errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.VALIDATION) -> ClassifiedError:
        return ClassifiedError.from_category(
            category=category,
            message=self.message,
            details=self.details,
        )


class LockContentionError(OrchestrationError):
    """Raised when an exclusive worker lock cannot be acquired."""

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.PERMISSION) -> ClassifiedError:
        return ClassifiedError(
            category=category,
            message=self.message,
            recoverable=True,
            details={"code": "lock_contention", **self.details},
        )


class LockAccessError(LockContentionError):
    """Raised when opening or accessing the lock file fails due to permissions or OS I/O error."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)
        self.is_access_denied = True

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.PERMISSION) -> ClassifiedError:
        return ClassifiedError(
            category=category,
            message=self.message,
            recoverable=False,
            details={"code": "lock_access_denied", **self.details},
        )


class PreflightValidationError(OrchestrationError):
    """Raised when preflight validation detects missing, invalid, or conflicting configuration."""

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.VALIDATION) -> ClassifiedError:
        return ClassifiedError(
            category=category,
            message=self.message,
            recoverable=False,
            details={"code": "preflight_validation_error", **self.details},
        )


class MissingComponentError(OrchestrationError):
    """Raised when a required integration component or service is absent."""

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.MISSING_CONFIGURATION) -> ClassifiedError:
        return ClassifiedError(
            category=category,
            message=self.message,
            recoverable=False,
            details={"code": "missing_component", **self.details},
        )


class StaleInputError(OrchestrationError):
    """Raised when resuming a run with modified inputs or incompatible versions."""

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.VALIDATION) -> ClassifiedError:
        return ClassifiedError(
            category=category,
            message=self.message,
            recoverable=False,
            details={"code": "stale_input_error", **self.details},
        )


class ExecutionInterruptedError(OrchestrationError):
    """Raised when execution is interrupted by signal or cancellation."""

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.TRANSIENT_NETWORK) -> ClassifiedError:
        return ClassifiedError(
            category=category,
            message=self.message,
            recoverable=True,
            details={"code": "execution_interrupted", **self.details},
        )


class StageExecutionError(OrchestrationError):
    """Raised when a stage encounters an unhandled fatal error."""

    def to_classified_error(self, category: ErrorCategory = ErrorCategory.VALIDATION) -> ClassifiedError:
        return ClassifiedError(
            category=category,
            message=self.message,
            recoverable=False,
            details={"code": "stage_execution_error", **self.details},
        )
