"""Custom storage layer exceptions."""

from __future__ import annotations


class StorageError(Exception):
    """Base exception for all storage and database errors."""


class DuplicateKeyError(StorageError):
    """Raised when a uniqueness constraint is violated (e.g. source key, canonical ID)."""

    def __init__(self, message: str, constraint: str | None = None) -> None:
        super().__init__(message)
        self.constraint = constraint


class MigrationError(StorageError):
    """Raised when a schema migration fails or is invalid."""


class RecordNotFoundError(StorageError):
    """Raised when an expected record is not found in the database."""


class TransactionError(StorageError):
    """Raised when a transaction fails or cannot be rolled back cleanly."""

