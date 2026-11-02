"""Unit tests for backup failure modes, corruption detection, and isolation (OPS-01-S06)."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.operations.backup import create_backup
from job_automation.operations.exceptions import BackupError
from job_automation.operations.records import OperationsSettings
from job_automation.operations.verification import verify_backup
from job_automation.storage.engine import StorageEngine


def test_verify_backup_detects_tampered_file(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    dest_dir = tmp_path / "backup"
    dest_dir.mkdir()

    # Create dummy raw file
    raw_dir = data_root / "raw"
    raw_dir.mkdir()
    raw_file = raw_dir / "sample.json"
    raw_file.write_text('{"clean": true}', encoding="utf-8")

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=raw_dir,
    )
    engine.migrate()

    settings = OperationsSettings()
    manifest, backup_dir = create_backup(
        settings=settings,
        data_root=data_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    # Tamper with copied file in backup directory
    tampered_file = backup_dir / "raw" / "sample.json"
    tampered_file.write_text('{"tampered": true}', encoding="utf-8")

    # Verification must catch the checksum mismatch
    is_valid, issues = verify_backup(backup_dir)
    assert is_valid is False
    assert any("Content hash mismatch" in i for i in issues)


def test_verify_backup_detects_missing_complete_marker(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    dest_dir = tmp_path / "backup"
    dest_dir.mkdir()

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
    )
    engine.migrate()

    settings = OperationsSettings()
    manifest, backup_dir = create_backup(
        settings=settings,
        data_root=data_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    # Remove completion marker
    (backup_dir / "backup.complete").unlink()

    is_valid, issues = verify_backup(backup_dir)
    assert is_valid is False
    assert any("backup.complete" in i for i in issues)


def test_backup_rejects_payload_dir_destination(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    raw_dir = data_root / "raw"
    raw_dir.mkdir()

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=raw_dir,
    )
    engine.migrate()

    settings = OperationsSettings()
    with pytest.raises(ValueError, match="overlaps with managed payload directory"):
        create_backup(
            settings=settings,
            data_root=data_root,
            engine=engine,
            destination_override=raw_dir,
            local_only=True,
        )

