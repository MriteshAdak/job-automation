"""Abstract ports and interfaces for operations (OPS-01)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import uuid

from job_automation.operations.records import (
    BackupManifest,
    CapacityReport,
    CleanupPlan,
    CleanupResult,
    MaintenanceReport,
    OperationsSettings,
    RemoteRecoveryExport,
    RestorePlan,
    RestoreResult,
    RetentionInventory,
)
from job_automation.storage.engine import StorageEngine


@runtime_checkable
class RetentionInventoryPort(Protocol):
    """Protocol for scanning storage inventory and computing reference/protection graph."""

    def build_inventory(
        self, data_root: Path, engine: StorageEngine
    ) -> RetentionInventory:
        """Scan deployment storage and produce a complete inventory."""
        ...


@runtime_checkable
class CapacityPort(Protocol):
    """Protocol for measuring filesystem and remote quota capacity."""

    def check_capacity(
        self,
        settings: OperationsSettings,
        source_root: Path,
        destination_path: Path | None = None,
        staging_path: Path | None = None,
        estimated_required_bytes: int = 0,
    ) -> CapacityReport:
        """Measure available capacity and evaluate against configured reserves."""
        ...


@runtime_checkable
class CleanupPort(Protocol):
    """Protocol for previewing and executing cleanup plans."""

    def plan_cleanup(
        self,
        inventory: RetentionInventory,
        settings: OperationsSettings,
        cutoff: datetime | None = None,
    ) -> CleanupPlan:
        """Generate a reviewable, non-mutating cleanup plan."""
        ...

    def apply_cleanup(
        self,
        plan: CleanupPlan,
        settings: OperationsSettings,
        data_root: Path,
        engine: StorageEngine,
    ) -> CleanupResult:
        """Safely execute a reviewed cleanup plan under maintenance lock."""
        ...


@runtime_checkable
class RemoteRecoveryPort(Protocol):
    """Protocol for assembling remote export coverage."""

    def capture_remote_export(
        self,
        engine: StorageEngine,
        config: Any | None = None,
    ) -> RemoteRecoveryExport:
        """Extract candidate-owned Salesforce snapshots and export artifacts."""
        ...


@runtime_checkable
class BackupPort(Protocol):
    """Protocol for creating and verifying backup sets."""

    def create_backup(
        self,
        settings: OperationsSettings,
        data_root: Path,
        engine: StorageEngine,
        local_only: bool = False,
    ) -> tuple[BackupManifest, Path]:
        """Create a complete, mutually consistent backup set in staging then commit."""
        ...

    def verify_backup(
        self, backup_path: Path
    ) -> tuple[bool, list[str]]:
        """Verify the integrity, file hashes, and SQLite consistency of a backup set."""
        ...


@runtime_checkable
class RestorePort(Protocol):
    """Protocol for isolated recovery and path relocation."""

    def plan_restore(
        self, backup_path: Path, target_data_root: Path
    ) -> RestorePlan:
        """Validate backup and plan path relocation into an isolated target root."""
        ...

    def apply_restore(
        self, plan: RestorePlan
    ) -> RestoreResult:
        """Execute restore and verification into the target root."""
        ...

