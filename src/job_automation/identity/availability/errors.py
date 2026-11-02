"""Exception hierarchy for IDENTITY-02 availability tracking."""

from __future__ import annotations


class AvailabilityError(Exception):
    """Base exception for all availability tracking errors."""


class AvailabilityConfigurationError(AvailabilityError):
    """Raised when availability configuration or thresholds are invalid."""


class AvailabilityScopeError(AvailabilityError):
    """Raised when inventory scope is invalid or mismatched."""


class AvailabilityConflictError(AvailabilityError):
    """Raised when immutable evidence or manifest content conflicts during consumption."""


class AvailabilityLedgerError(AvailabilityError):
    """Raised when persistence or transaction boundaries fail in the availability ledger."""

