"""Tests for validation issues and classified errors."""

from __future__ import annotations

import pytest

from job_automation.contracts.errors import (
    ClassifiedError,
    ErrorCategory,
    RECOVERABLE_CATEGORIES,
    ValidationIssue,
)


class TestErrors:
    def test_validation_issue_fields(self) -> None:
        vi = ValidationIssue(
            field_path="title",
            code="missing_required_field",
            message="Title is required and cannot be empty",
            severity="error",
        )
        assert vi.field_path == "title"
        assert vi.code == "missing_required_field"
        assert vi.severity == "error"

    def test_classified_error_recoverability(self) -> None:
        err_transient = ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_NETWORK,
            "Network timeout connecting to endpoint",
        )
        assert err_transient.recoverable is True
        assert err_transient.category == ErrorCategory.TRANSIENT_NETWORK

        err_rate_limit = ClassifiedError.from_category(
            ErrorCategory.RATE_LIMIT,
            "HTTP 429 Too Many Requests",
        )
        assert err_rate_limit.recoverable is True

        err_validation = ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            "Invalid field payload",
            field_path="locations[0].city",
        )
        assert err_validation.recoverable is False
        assert err_validation.field_path == "locations[0].city"

        err_auth = ClassifiedError.from_category(
            ErrorCategory.AUTHENTICATION,
            "Invalid credentials provided",
        )
        assert err_auth.recoverable is False

    def test_recoverable_categories_membership(self) -> None:
        assert ErrorCategory.RATE_LIMIT in RECOVERABLE_CATEGORIES
        assert ErrorCategory.TRANSIENT_NETWORK in RECOVERABLE_CATEGORIES
        assert ErrorCategory.TRANSIENT_SERVICE in RECOVERABLE_CATEGORIES
        assert ErrorCategory.CAPACITY in RECOVERABLE_CATEGORIES

        assert ErrorCategory.VALIDATION not in RECOVERABLE_CATEGORIES
        assert ErrorCategory.MISSING_CONFIGURATION not in RECOVERABLE_CATEGORIES
        assert ErrorCategory.PERMISSION not in RECOVERABLE_CATEGORIES
        assert ErrorCategory.AUTHENTICATION not in RECOVERABLE_CATEGORIES
        assert ErrorCategory.CONTEXT_BUDGET not in RECOVERABLE_CATEGORIES
        assert ErrorCategory.MODEL_OUTPUT not in RECOVERABLE_CATEGORIES
        assert ErrorCategory.UNSUPPORTED_INPUT not in RECOVERABLE_CATEGORIES

