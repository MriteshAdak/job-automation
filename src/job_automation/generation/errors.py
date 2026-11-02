"""GEN-01 exception hierarchy."""

from __future__ import annotations

from typing import Any


class GenerationError(Exception):
    """Base exception for all generation workflow errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class MissingComponentError(GenerationError):
    """Raised when a required component (GEN-02, GEN-03, GEN-04, GEN-05, GEN-06) is not configured."""
    pass


class DependencyBlockedError(GenerationError):
    """Raised when a generation stage cannot advance due to an unfulfilled external dependency."""
    pass


class FreezeConflictError(GenerationError):
    """Raised when attempting to re-freeze an already frozen request with conflicting options or manifests."""
    pass


class InvalidRequestStateError(GenerationError):
    """Raised when a request is in an unexpected state for the attempted operation."""
    pass


class ProjectionUncertainError(GenerationError):
    """Raised when a remote projection mutation has an uncertain outcome and blocks subsequent state writes."""
    pass


class OptionMismatchError(GenerationError):
    """Raised when a retry attempts to mutate immutable request options."""
    pass


class StaleWorkerError(GenerationError):
    """Raised when remote request ownership is claimed by another worker."""
    pass


class PreflightFailureError(GenerationError):
    """Raised when request preflight validation fails (e.g. job_unavailable)."""
    pass

