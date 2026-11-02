"""Error categories and exceptions for the evaluation subsystem (EVAL-01-S01).

Enforces:
- Classified error mappings.
- Strict detection of arm control mismatches, publication attempts, database aliasing, and data leakage.
"""

from __future__ import annotations

from typing import Any
from job_automation.contracts.errors import ClassifiedError, ErrorCategory


class EvaluationError(Exception):
    """Base exception for evaluation subsystem failures."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            self.message,
            details=self.details,
        )


class MismatchedArmControlError(EvaluationError):
    """Raised when JSON and RAG arms within a pair do not share identical controls."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            f"Mismatched controls in evaluation pair: {self.message}",
            details=self.details,
        )


class PublicationAttemptBlockedError(EvaluationError):
    """Raised when evaluation code or configuration attempts Salesforce publication."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.PERMISSION,
            f"Publication blocked: {self.message}",
            details=self.details,
        )


class DatabaseAliasingError(EvaluationError):
    """Raised when evaluation database path aliases or collides with production database."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            f"Database aliasing collision: {self.message}",
            details=self.details,
        )


class InputTamperingError(EvaluationError):
    """Raised when recorded input hash does not match computed input bytes."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            f"Input tampering or hash mismatch: {self.message}",
            details=self.details,
        )


class InvalidCorpusError(EvaluationError):
    """Raised when evaluation corpus contains invalid spans, missing references, or orphan facts."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            f"Invalid corpus annotation: {self.message}",
            details=self.details,
        )


class CorpusSplitLeakageError(EvaluationError):
    """Raised when identical canonical jobs or duplicate variants cross split boundaries."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            f"Corpus split leakage: {self.message}",
            details=self.details,
        )


class UnadjudicatedReviewError(EvaluationError):
    """Raised when unadjudicated review corrections are applied without adjudication."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            f"Unadjudicated review correction: {self.message}",
            details=self.details,
        )


class UnavailablePhase1ExtensionError(EvaluationError):
    """Raised when Phase 1 document drafting or rendering evaluation is requested."""

    def to_classified_error(self) -> ClassifiedError:
        return ClassifiedError.from_category(
            ErrorCategory.MISSING_CONFIGURATION,
            f"Phase 1 evaluation extension is deferred and unavailable: {self.message}",
            details=self.details,
        )
