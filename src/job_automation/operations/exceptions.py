"""Exception classes for operations errors (OPS-01)."""

from __future__ import annotations

from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory


class OperationsError(Exception):
    """Base exception for all operations and maintenance failures."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.VALIDATION,
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.recoverable = recoverable
        self.details = details or {}
        self.classified_error = ClassifiedError(
            category=category,
            message=message,
            recoverable=recoverable,
            details=self.details,
        )


class PlanInvalidatedError(OperationsError):
    """Raised when a cleanup plan or restore plan is invalidated by underlying state changes."""
    pass


class BackupError(OperationsError):
    """Raised on backup creation or verification failure."""
    pass


class RestoreError(OperationsError):
    """Raised on restore planning, verification, or application failure."""
    pass

