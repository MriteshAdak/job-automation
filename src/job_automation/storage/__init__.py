"""Storage package for durable SQLite persistence, filestore, and migrations."""

from __future__ import annotations

from job_automation.storage.connection import open_connection, transaction
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import (
    DuplicateKeyError,
    MigrationError,
    RecordNotFoundError,
    StorageError,
    TransactionError,
)
from job_automation.storage.filestore import Filestore, compute_sha256, sanitize_filename
from job_automation.storage.migrations import (
    apply_migrations,
    get_applied_migrations,
    get_current_schema_version,
)

__all__ = [
    "DuplicateKeyError",
    "Filestore",
    "MigrationError",
    "RecordNotFoundError",
    "StorageEngine",
    "StorageError",
    "TransactionError",
    "apply_migrations",
    "compute_sha256",
    "get_applied_migrations",
    "get_current_schema_version",
    "open_connection",
    "sanitize_filename",
    "transaction",
]

