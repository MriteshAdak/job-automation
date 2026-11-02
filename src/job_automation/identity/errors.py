"""Exceptions for identity resolution, review, and merge operations."""

from __future__ import annotations


class IdentityError(Exception):
    """Base exception for identity domain operations."""


class ConflictError(IdentityError):
    """Raised when contradictory evidence (e.g. conflicting requisitions) prevents linking."""


class InvalidOperationError(IdentityError):
    """Raised when an operation is invalid (e.g. merging a job with itself)."""


class MergeError(IdentityError):
    """Raised when a merge operation fails or is rejected."""


class ReversalError(IdentityError):
    """Raised when a merge reversal operation fails (e.g. already reversed)."""


class ReviewCaseNotFoundError(IdentityError):
    """Raised when a specified review case is not found."""

