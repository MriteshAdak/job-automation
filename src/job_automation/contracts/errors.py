"""Structured validation issues and classified error contracts.

Distinguishes error categories, indicates recoverability, and ensures
safe messages without echoing secret tokens or raw payloads.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from job_automation.contracts.base import ContractModel


class ErrorCategory(StrEnum):
    """Classified error category for failure handling and recovery."""

    VALIDATION = "validation"
    MISSING_CONFIGURATION = "missing_configuration"
    PERMISSION = "permission"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TRANSIENT_NETWORK = "transient_network"
    TRANSIENT_SERVICE = "transient_service"
    CONTEXT_BUDGET = "context_budget"
    MODEL_OUTPUT = "model_output"
    CAPACITY = "capacity"
    UNSUPPORTED_INPUT = "unsupported_input"


# Recoverable error categories that warrant bounded retry with backoff.
RECOVERABLE_CATEGORIES: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.TRANSIENT_NETWORK,
        ErrorCategory.TRANSIENT_SERVICE,
        ErrorCategory.CAPACITY,
    }
)


class ValidationIssue(ContractModel):
    """Structured validation issue with contract field path and safe message."""

    field_path: str = Field(
        description="Path to the offending field (e.g. 'title' or 'locations[0].city')"
    )
    code: str = Field(
        description="Machine-readable issue code (e.g. 'missing_required_field', 'invalid_format')"
    )
    message: str = Field(
        description="Safe diagnostic message free of credentials or raw secret payloads"
    )
    severity: Literal["error", "warning"] = "error"


class ClassifiedError(ContractModel):
    """Classified operational or domain error.

    Distinguishes recoverable failures from permanent errors and maps
    to the system error taxonomy without arbitrary tool or shell authority.
    """

    category: ErrorCategory
    message: str = Field(
        description="Safe diagnostic message without credentials or tokens"
    )
    recoverable: bool = Field(
        description="Whether this error category is eligible for bounded retry"
    )
    field_path: str | None = Field(
        default=None,
        description="Optional field path if the error pertains to a specific field",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Safe non-sensitive contextual details",
    )

    @classmethod
    def from_category(
        cls,
        category: ErrorCategory,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ClassifiedError:
        """Create a ClassifiedError with automatic recoverability detection."""
        return cls(
            category=category,
            message=message,
            recoverable=category in RECOVERABLE_CATEGORIES,
            field_path=field_path,
            details=details,
        )

    @classmethod
    def validation(cls, message: str, **kwargs: Any) -> ClassifiedError:
        return cls.from_category(ErrorCategory.VALIDATION, message, **kwargs)

    @classmethod
    def transient_network(cls, message: str, **kwargs: Any) -> ClassifiedError:
        return cls.from_category(ErrorCategory.TRANSIENT_NETWORK, message, **kwargs)

    @classmethod
    def not_found(cls, message: str, **kwargs: Any) -> ClassifiedError:
        return cls.from_category(ErrorCategory.VALIDATION, message, **kwargs)

    @classmethod
    def permission(cls, message: str, **kwargs: Any) -> ClassifiedError:
        return cls.from_category(ErrorCategory.PERMISSION, message, **kwargs)

