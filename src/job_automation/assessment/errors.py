"""Domain exceptions for MATCH-01 assessment boundary."""

from __future__ import annotations


class AssessmentError(Exception):
    """Base exception for all assessment errors."""


class AssessmentInputError(AssessmentError):
    """Raised when evaluation inputs fail validation or prerequisite contracts.

    Examples: unapproved profile snapshot, invalid search policy,
    mismatched posting revision, or corrupted normalized posting.
    """


class AssessmentConfigurationError(AssessmentError):
    """Raised when policy criteria specify unsupported or ambiguous configuration.

    Examples: unsupported operators on target fields, invalid salary operand formats,
    or ambiguous operand definitions.
    """


class FieldEvaluationError(AssessmentError):
    """Raised when an individual target field cannot be evaluated."""

