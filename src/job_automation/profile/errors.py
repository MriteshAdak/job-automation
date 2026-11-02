"""Domain errors for the candidate profile component.

All errors provide safe, classified diagnostics without exposing raw candidate
payloads, personal data, or sensitive claim texts.
"""

from __future__ import annotations


class ProfileError(Exception):
    """Base exception for all profile-related errors."""


class ProfileValidationError(ProfileError):
    """Raised when profile draft or snapshot fails invariant validation."""

    def __init__(self, message: str, field_path: str | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.field_path = field_path
        self.code = code


class ProfileApprovalError(ProfileError):
    """Raised when an approval attempt violates publication rules or integrity checks."""


class ProfileConflictError(ProfileError):
    """Raised when a version conflict, digest mismatch, or stale review occurs."""


class ProfileNotFoundError(ProfileError):
    """Raised when a requested profile version or draft is not found."""


class FactNotFoundError(ProfileError):
    """Raised when an evidence fact reference cannot be resolved in a specific version."""


class InclusionConflictError(ProfileError):
    """Raised when mandatory context cannot be satisfied under the requested inclusion rules."""


class EvidenceStoreError(ProfileError):
    """Raised when evidence file operations, hashing, or path validations fail."""

