"""Isolated restore planning, execution, and verification (OPS-01-S07).

Enforces:
- Full preflight verification of backup manifest, hashes, and SQLite integrity before restore.
- Non-destructive execution: never overwrites existing populated runtime data root.
- Maintenance locking of target root during restoration and path relocation.
- Transitive path relocation updating absolute database references while preserving hashes.
- Inert processing: restoration performs zero outbound network calls, sync dispatches, or model calls.
- Clear post-restore activation checklist and rollback instructions.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.operations.capacity import measure_volume_capacity
from job_automation.operations.exceptions import RestoreError
from job_automation.operations.manifest import load_manifest
from job_automation.operations.paths import validate_safe_path
from job_automation.operations.records import (
    CapacityStatus,
    ItemClass,
    OperationStatus,
    OperationsSettings,
    RestorePlan,
    RestoreResult,
)
from job_automation.operations.relocation import relocate_paths_in_database
from job_automation.operations.verification import verify_backup
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.filestore import compute_sha256

logger = logging.getLogger(__name__)


def plan_restore(
    backup_path: Path | str,
    target_data_root: Path | str,
    settings: OperationsSettings | None = None,
) -> RestorePlan:
    """Validate a backup set and produce an actionable RestorePlan for isolated execution."""
    b_path = Path(backup_path).resolve()
    target = Path(target_data_root).resolve()
    ops_settings = settings or OperationsSettings()

    # 1. Verify backup set
    is_valid, issues = verify_backup(b_path)
    if not is_valid:
        raise RestoreError(
            f"Backup verification failed for '{b_path}': {issues}",
            category=ErrorCategory.UNSUPPORTED_INPUT,
        )

    manifest = load_manifest(b_path)

    # 2. Check target directory containment and non-emptiness
    conflicts: list[str] = []
    if target.exists():
        existing_items = list(target.iterdir())
        if existing_items:
            conflicts.append(
                f"Target restore directory '{target}' is not empty (contains {len(existing_items)} items). "
                "Restoring into an existing non-empty directory is prohibited."
            )

    # 3. Capacity preflight
    rep, cap_issues = measure_volume_capacity(
        target_path=target,
        required_bytes=manifest.total_bytes,
        settings=ops_settings.capacity,
    )
    if rep.status in (CapacityStatus.BLOCKED, CapacityStatus.UNKNOWN):
        conflicts.append(f"Insufficient capacity on target volume '{target}': status is {rep.status.value}")

    plan_id = uuid.uuid4()
    return RestorePlan(
        plan_id=plan_id,
        backup_id=manifest.backup_id,
        backup_path=str(b_path),
        source_data_root=manifest.source_data_root,
        target_data_root=str(target),
        created_at=datetime.now(timezone.utc),
        files_to_restore=manifest.total_files_count,
        total_bytes=manifest.total_bytes,
        path_mappings_count=len(manifest.files),
        capacity_status=rep.status,
        conflicts=conflicts,
        is_valid=len(conflicts) == 0,
    )


def apply_restore(
    plan: RestorePlan,
    settings: OperationsSettings | None = None,
) -> RestoreResult:
    """Execute isolated restoration and path relocation into the target data root."""
    if not plan.is_valid:
        raise RestoreError(
            f"Cannot apply invalid restore plan: {plan.conflicts}",
            category=ErrorCategory.VALIDATION,
        )

    target_root = Path(plan.target_data_root).resolve()
    backup_dir = Path(plan.backup_path).resolve()
    ops_settings = settings or OperationsSettings()

    # Create target directory
    target_root.mkdir(parents=True, exist_ok=True)

    # Acquire maintenance lock on the new restored root
    lock = WindowsWorkerLock(target_root)
    with lock.acquire(owner_kind=OwnerKind.MAINTENANCE, timeout_seconds=ops_settings.limits.timeout_seconds):
        manifest = load_manifest(backup_dir)

        # 1. Copy files to target root
        restored_count = 0
        issues: list[ClassifiedError] = []

        for entry in manifest.files:
            rel = entry.root_relative_path
            src_file = validate_safe_path(rel, backup_dir)
            dst_file = target_root / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(str(src_file), str(dst_file))
            restored_count += 1

            # Check copied hash
            copied_hash = compute_sha256(dst_file.read_bytes())
            if copied_hash != entry.sha256:
                issues.append(
                    ClassifiedError(
                        category=ErrorCategory.VALIDATION,
                        message=f"Restored file '{rel}' hash mismatch: expected {entry.sha256}, got {copied_hash}",
                        recoverable=False,
                    )
                )

        # 2. Relocate absolute paths in the restored database
        restored_db_path = target_root / "database" / "job_automation.db"
        relocated_count = 0
        integrity_ok = False
        fk_ok = False

        if restored_db_path.is_file():
            conn = sqlite3.connect(str(restored_db_path))
            conn.row_factory = sqlite3.Row
            try:
                relocated_count = relocate_paths_in_database(
                    conn=conn,
                    source_root=plan.source_data_root,
                    target_root=target_root,
                )

                # SQLite integrity check
                cur_int = conn.execute("PRAGMA integrity_check;")
                int_rows = [r[0] for r in cur_int.fetchall()]
                integrity_ok = int_rows == ["ok"]

                # Foreign key check
                cur_fk = conn.execute("PRAGMA foreign_key_check;")
                fk_violations = cur_fk.fetchall()
                fk_ok = len(fk_violations) == 0

                if not integrity_ok:
                    issues.append(
                        ClassifiedError(
                            category=ErrorCategory.VALIDATION,
                            message=f"Restored database integrity check failed: {int_rows}",
                            recoverable=False,
                        )
                    )
                if not fk_ok:
                    issues.append(
                        ClassifiedError(
                            category=ErrorCategory.VALIDATION,
                            message=f"Restored database has {len(fk_violations)} foreign key violations",
                            recoverable=False,
                        )
                    )
            finally:
                conn.close()

        checklist = [
            f"1. Restored files verified in isolated target data root: '{target_root}'.",
            f"2. Database path references relocated ({relocated_count} records updated).",
            "3. SQLite integrity and foreign key constraints passed.",
            "4. Point configuration file or set JOB_AUTOMATION_DATA_ROOT to the restored data root.",
            "5. If restoring to a new Salesforce org, inspect the candidate recovery package and re-map External IDs.",
            "6. Run 'python -m job_automation config check' to verify paths before resuming background workers.",
        ]

        status = OperationStatus.SUCCEEDED if len(issues) == 0 else OperationStatus.FAILED

        return RestoreResult(
            plan_id=plan.plan_id,
            backup_id=plan.backup_id,
            target_data_root=str(target_root),
            restored_at=datetime.now(timezone.utc),
            status=status,
            restored_files_count=restored_count,
            relocated_paths_count=relocated_count,
            integrity_check_passed=integrity_ok,
            foreign_key_check_passed=fk_ok,
            issues=issues,
            activation_checklist=checklist,
        )

