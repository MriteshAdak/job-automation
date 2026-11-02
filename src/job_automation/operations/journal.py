"""Cleanup journal management and crash-recovery procedures (OPS-01-S04)."""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_automation.operations.paths import validate_safe_path
from job_automation.operations.records import ItemClass, ProtectionReason
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class CleanupJournalManager:
    """Manages transactional cleanup journal entries and interruption recovery."""

    def __init__(self, engine: StorageEngine, data_root: Path | str) -> None:
        self.engine = engine
        self.data_root = Path(data_root).resolve()

    def record_step(
        self,
        plan_id: uuid.UUID,
        step_number: int,
        item_path: str,
        stage: str,
        status: str,
        reclaimed_bytes: int = 0,
        details: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        """Record or update a journal step participating safely in outer transactions."""
        journal_id = uuid.uuid5(plan_id, f"{step_number}:{stage}")
        self.engine.operations.record_cleanup_journal_step(
            journal_id=journal_id,
            plan_id=plan_id,
            step_number=step_number,
            item_path=item_path,
            stage=stage,
            status=status,
            reclaimed_bytes=reclaimed_bytes,
            details=details,
        )
        return journal_id

    def recover_incomplete_journals(self) -> dict[str, int]:
        """Inspect and safely resolve any incomplete cleanup journal entries after process restart.

        Returns counts of reconciled items: {'restored': int, 'deleted': int, 'errors': int}
    """
        incomplete = self.engine.operations.get_incomplete_journals()
        restored_count = 0
        deleted_count = 0
        error_count = 0

        for entry in incomplete:
            plan_id = uuid.UUID(entry["plan_id"])
            journal_id = uuid.UUID(entry["journal_id"])
            item_rel = entry["item_path"]
            stage = entry["stage"]
            status = entry["status"]

            quarantine_dir = self.data_root / ".cleanup_quarantine" / str(plan_id)
            quarantine_file = quarantine_dir / Path(item_rel).name
            original_file = validate_safe_path(item_rel, self.data_root)

            try:
                if quarantine_file.exists():
                    # If quarantined but not deleted, determine if original is now needed/referenced
                    # Default safe behavior: if original doesn't exist, restore it to safety
                    if not original_file.exists():
                        original_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(quarantine_file), str(original_file))
                        self.engine.operations.record_cleanup_journal_step(
                            journal_id=journal_id,
                            plan_id=plan_id,
                            step_number=entry["step_number"],
                            item_path=item_rel,
                            stage="restored",
                            status="completed",
                            reclaimed_bytes=0,
                            details={"recovered_from_interruption": True},
                        )
                        restored_count += 1
                    else:
                        # Original already exists; safe to delete duplicate from quarantine
                        quarantine_file.unlink()
                        deleted_count += 1
                else:
                    # Quarantine file does not exist; mark completed
                    self.engine.operations.record_cleanup_journal_step(
                        journal_id=journal_id,
                        plan_id=plan_id,
                        step_number=entry["step_number"],
                        item_path=item_rel,
                        stage=stage,
                        status="completed",
                        reclaimed_bytes=entry.get("reclaimed_bytes", 0),
                        details={"reconciled_missing_quarantine": True},
                    )
            except Exception as exc:
                logger.error("Failed to recover cleanup journal entry %s: %s", journal_id, exc)
                error_count += 1

        # Cleanup empty quarantine directories
        quarantine_base = self.data_root / ".cleanup_quarantine"
        if quarantine_base.exists():
            for p_dir in list(quarantine_base.iterdir()):
                if p_dir.is_dir() and not any(p_dir.iterdir()):
                    try:
                        p_dir.rmdir()
                    except OSError:
                        pass

        return {
            "restored": restored_count,
            "deleted": deleted_count,
            "errors": error_count,
        }

