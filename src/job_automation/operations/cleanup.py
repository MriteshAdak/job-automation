"""Safe cleanup application and quarantine execution under maintenance exclusion (OPS-01-S04).

Enforces:
- Maintenance lock acquisition excluding all concurrent writers.
- Plan verification: plan hash, expiration, store fingerprint, and candidate hashes.
- Fresh inventory verification: any candidate newly referenced since preview aborts execution.
- Staged reversible movement into quarantine before unlinking.
- Transaction-participating journaling and accurate actual reclaimed byte accounting.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.operations.exceptions import OperationsError, PlanInvalidatedError
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.operations.journal import CleanupJournalManager
from job_automation.operations.paths import validate_safe_path
from job_automation.operations.records import (
    CleanupPlan,
    CleanupResult,
    ItemClass,
    OperationStatus,
    OperationsSettings,
)
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine
from job_automation.storage.filestore import compute_sha256

logger = logging.getLogger(__name__)


def apply_cleanup(
    plan_id: uuid.UUID,
    plan_hash: str,
    settings: OperationsSettings,
    data_root: Path | str,
    engine: StorageEngine,
) -> CleanupResult:
    """Safely apply a reviewed cleanup plan under exclusive maintenance lock."""
    root = Path(data_root).resolve()
    lock = WindowsWorkerLock(root)

    # Exclude all other writers
    with lock.acquire(owner_kind=OwnerKind.MAINTENANCE, timeout_seconds=settings.limits.timeout_seconds):
        now_dt = datetime.now(timezone.utc)

        # 1. Fetch and validate plan
        plan_record = engine.operations.get_cleanup_plan(plan_id)
        if not plan_record:
            raise OperationsError(
                category=ErrorCategory.UNSUPPORTED_INPUT,
                message=f"Cleanup plan {plan_id} not found in database",
                recoverable=False,
            )

        if plan_record["status"] != "planned":
            raise OperationsError(
                category=ErrorCategory.UNSUPPORTED_INPUT,
                message=f"Cleanup plan {plan_id} cannot be applied: status is '{plan_record['status']}'",
                recoverable=False,
            )

        plan = CleanupPlan.model_validate_json(plan_record["plan_json"])

        if plan.plan_hash != plan_hash:
            raise OperationsError(
                category=ErrorCategory.VALIDATION,
                message=f"Supplied plan hash '{plan_hash}' does not match registered plan hash '{plan.plan_hash}'",
                recoverable=False,
            )

        if now_dt > plan.expires_at:
            engine.operations.update_cleanup_plan_status(plan_id, "expired")
            raise OperationsError(
                category=ErrorCategory.UNSUPPORTED_INPUT,
                message=f"Cleanup plan {plan_id} expired at {plan.expires_at.isoformat()}",
                recoverable=False,
            )

        # 2. Fresh inventory & protection recheck
        mgr = RetentionInventoryManager(root)
        fresh_inv = mgr.build_inventory(engine)

        if fresh_inv.store_fingerprint != plan.store_fingerprint:
            engine.operations.update_cleanup_plan_status(plan_id, "invalidated")
            raise PlanInvalidatedError(
                category=ErrorCategory.VALIDATION,
                message=(
                    f"Store state changed since preview: expected fingerprint '{plan.store_fingerprint}', "
                    f"got '{fresh_inv.store_fingerprint}'. Plan invalidated."
                ),
                recoverable=False,
            )

        fresh_protected = {
            it.root_relative_path
            for it in fresh_inv.items
            if it.is_protected or it.is_referenced
        }

        for cand in plan.candidates:
            if cand.root_relative_path in fresh_protected:
                engine.operations.update_cleanup_plan_status(plan_id, "invalidated")
                raise PlanInvalidatedError(
                    category=ErrorCategory.VALIDATION,
                    message=(
                        f"Candidate '{cand.root_relative_path}' has become referenced or protected "
                        f"since preview. Plan invalidated to prevent data loss."
                    ),
                    recoverable=False,
                )

        # 3. Execute cleanup through reversible quarantine
        quarantine_dir = root / ".cleanup_quarantine" / str(plan_id)
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        journal_mgr = CleanupJournalManager(engine, root)

        attempted = 0
        deleted = 0
        skipped = 0
        failed = 0
        actual_reclaimed = 0
        issues: list[ClassifiedError] = []

        # Stage 1: Move to quarantine
        quarantined_files: list[tuple[int, Path, Path, int]] = []
        for step_idx, cand in enumerate(plan.candidates, start=1):
            attempted += 1
            source_file = validate_safe_path(cand.root_relative_path, root)
            if not source_file.exists():
                skipped += 1
                journal_mgr.record_step(
                    plan_id=plan_id,
                    step_number=step_idx,
                    item_path=cand.root_relative_path,
                    stage="quarantined",
                    status="skipped",
                    details={"reason": "File already removed or missing"},
                )
                continue

            # Verify file content hash before touching
            try:
                curr_bytes = source_file.read_bytes()
                curr_hash = compute_sha256(curr_bytes)
                if curr_hash != cand.expected_hash:
                    skipped += 1
                    issues.append(
                        ClassifiedError(
                            category=ErrorCategory.VALIDATION,
                            message=f"File '{cand.root_relative_path}' content hash changed since preview",
                            recoverable=False,
                        )
                    )
                    continue

                q_dest = quarantine_dir / f"{step_idx}_{source_file.name}"
                journal_mgr.record_step(
                    plan_id=plan_id,
                    step_number=step_idx,
                    item_path=cand.root_relative_path,
                    stage="quarantined",
                    status="in_progress",
                )

                shutil.move(str(source_file), str(q_dest))
                quarantined_files.append((step_idx, q_dest, source_file, len(curr_bytes)))

                journal_mgr.record_step(
                    plan_id=plan_id,
                    step_number=step_idx,
                    item_path=cand.root_relative_path,
                    stage="quarantined",
                    status="completed",
                    details={"quarantine_path": str(q_dest)},
                )
            except (OSError, PermissionError) as exc:
                failed += 1
                issues.append(
                    ClassifiedError(
                        category=ErrorCategory.PERMISSION,
                        message=f"Failed to quarantine file '{cand.root_relative_path}': {exc}",
                        recoverable=False,
                    )
                )

        # Stage 2: Permanently unlink quarantined files
        for step_idx, q_file, orig_file, size_b in quarantined_files:
            try:
                item_rel = orig_file.relative_to(root).as_posix()
                journal_mgr.record_step(
                    plan_id=plan_id,
                    step_number=step_idx,
                    item_path=item_rel,
                    stage="deleted",
                    status="in_progress",
                )

                if q_file.exists():
                    q_file.unlink()

                deleted += 1
                actual_reclaimed += size_b

                journal_mgr.record_step(
                    plan_id=plan_id,
                    step_number=step_idx,
                    item_path=item_rel,
                    stage="deleted",
                    status="completed",
                    reclaimed_bytes=size_b,
                )
            except (OSError, PermissionError) as exc:
                failed += 1
                issues.append(
                    ClassifiedError(
                        category=ErrorCategory.PERMISSION,
                        message=f"Failed to delete quarantined file '{q_file}': {exc}",
                        recoverable=False,
                    )
                )

        # Remove quarantine directory if clean
        try:
            if quarantine_dir.exists() and not any(quarantine_dir.iterdir()):
                quarantine_dir.rmdir()
        except OSError:
            pass

        final_status = (
            OperationStatus.SUCCEEDED
            if failed == 0 and len(issues) == 0
            else (OperationStatus.PARTIAL if deleted > 0 else OperationStatus.FAILED)
        )

        engine.operations.update_cleanup_plan_status(
            plan_id, "applied" if final_status == OperationStatus.SUCCEEDED else "partial"
        )

        return CleanupResult(
            plan_id=plan_id,
            plan_hash=plan_hash,
            applied_at=datetime.now(timezone.utc),
            status=final_status,
            attempted_count=attempted,
            deleted_count=deleted,
            skipped_count=skipped,
            failed_count=failed,
            actual_reclaimed_bytes=actual_reclaimed,
            issues=issues,
            quarantine_dir=str(quarantine_dir) if quarantine_dir.exists() else None,
        )
