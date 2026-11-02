"""Unit tests for cleanup interruption recovery and quarantine reconciliation (OPS-01-S04)."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.operations.journal import CleanupJournalManager
from job_automation.storage.engine import StorageEngine


def test_recover_interrupted_quarantine(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    db_path = data_root / "database" / "job_automation.db"
    (data_root / "raw").mkdir(parents=True)

    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    plan_id = uuid.uuid4()
    engine.operations.save_cleanup_plan(
        plan_id=plan_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        expires_at=datetime.now(timezone.utc).isoformat(),
        store_fingerprint="fp",
        policy_fingerprint="pfp",
        plan_hash="hash",
        status="planned",
        plan_json="{}",
    )

    journal_mgr = CleanupJournalManager(engine, data_root)

    # Simulate interruption: file was moved to quarantine, but process crashed before deletion
    item_rel = "raw/sample.json"
    orig_path = data_root / "raw" / "sample.json"

    quarantine_dir = data_root / ".cleanup_quarantine" / str(plan_id)
    quarantine_dir.mkdir(parents=True)
    quarantined_file = quarantine_dir / "sample.json"
    quarantined_file.write_text('{"quarantined": true}', encoding="utf-8")

    # Record incomplete journal step
    journal_mgr.record_step(
        plan_id=plan_id,
        step_number=1,
        item_path=item_rel,
        stage="quarantined",
        status="in_progress",
    )

    # Original file is currently missing
    assert not orig_path.exists()

    # Run crash recovery
    stats = journal_mgr.recover_incomplete_journals()

    assert stats["restored"] == 1
    assert stats["errors"] == 0

    # File must be restored to its original location
    assert orig_path.exists()
    assert orig_path.read_text(encoding="utf-8") == '{"quarantined": true}'

