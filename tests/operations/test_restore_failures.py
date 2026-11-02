"""Unit tests for restore failure modes and safety barriers (OPS-01-S07)."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.operations.backup import create_backup
from job_automation.operations.exceptions import RestoreError
from job_automation.operations.records import OperationsSettings
from job_automation.operations.restore import apply_restore, plan_restore
from job_automation.storage.engine import StorageEngine


def test_restore_refuses_non_empty_target(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    dest_dir = tmp_path / "bak"
    target_root = tmp_path / "tgt"
    src_root.mkdir()
    dest_dir.mkdir()
    target_root.mkdir()

    # Pre-populate target root with an existing file
    (target_root / "existing_file.txt").write_text("I already exist")

    engine = StorageEngine(db_path=src_root / "database" / "job_automation.db")
    engine.migrate()

    settings = OperationsSettings()
    manifest, backup_path = create_backup(
        settings=settings,
        data_root=src_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    plan = plan_restore(backup_path, target_root, settings)
    assert plan.is_valid is False
    assert any("not empty" in c for c in plan.conflicts)

    # Applying invalid plan raises RestoreError
    with pytest.raises(RestoreError, match="Cannot apply invalid restore plan"):
        apply_restore(plan, settings)


def test_restore_refuses_corrupted_backup(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    dest_dir = tmp_path / "bak"
    target_root = tmp_path / "tgt"
    src_root.mkdir()
    dest_dir.mkdir()

    engine = StorageEngine(db_path=src_root / "database" / "job_automation.db")
    engine.migrate()

    settings = OperationsSettings()
    manifest, backup_path = create_backup(
        settings=settings,
        data_root=src_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    # Corrupt database in backup
    db_file = backup_path / "database" / "job_automation.db"
    db_file.write_bytes(b"CORRUPTED SQLITE HEADER")

    # Planning restore from corrupted backup raises RestoreError
    with pytest.raises(RestoreError, match="Backup verification failed"):
        plan_restore(backup_path, target_root, settings)

