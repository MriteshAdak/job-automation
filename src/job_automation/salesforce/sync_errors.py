"""SYNC-01 domain exceptions and error categories.

Covers:
- Configuration and mapping issues (ownership collisions, invalid identifiers)
- State conflicts and barrier violations
- Selection and generation obsolescence
"""

from __future__ import annotations


class SyncError(Exception):
    """Base class for all SYNC-01 domain errors."""


class SyncMappingError(SyncError):
    """Error during field mapping or configuration validation."""


class SyncOwnershipError(SyncError):
    """Attempted to map machine fields onto candidate-owned fields or vice-versa."""


class SyncValidationError(SyncError):
    """Contract, identifier, or payload validation failure."""


class SyncConflictError(SyncError):
    """Conflicting concurrent update, fingerprint mismatch, or sequence race."""


class SyncBarrierError(SyncError):
    """Operation blocked by an active reconciliation or uncertainty barrier."""


class StaleSelectionError(SyncError):
    """Submitted assessment belongs to an older, superseded generation token."""

