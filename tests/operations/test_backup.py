"""Unit tests for backup creation, manifest verification, and pruning (OPS-01-S06)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.operations.backup import create_backup, prune_backups
from job_automation.operations.manifest import load_manifest
from job_automation.operations.records import OperationsSettings
from job_automation.operations.verification import verify_backup
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def populated_store(tmp_path: Path) -> tuple[StorageEngine, Path, Path]:
    data_root = tmp_path / "data_store"
    data_root.mkdir()
    dest_dir = tmp_path / "backup_dest"
    dest_dir.mkdir()

    db_path = data_root / "database" / "job_automation.db"
    raw_dir = data_root / "raw"
    artifacts_dir = data_root / "artifacts"
    profiles_dir = data_root / "profiles"
    indexes_dir = data_root / "indexes"

    for d in (raw_dir, artifacts_dir, profiles_dir, indexes_dir):
        d.mkdir(parents=True, exist_ok=True)

    engine = StorageEngine(
        db_path=db_path,
        raw_dir=raw_dir,
        artifacts_dir=artifacts_dir,
        profiles_dir=profiles_dir,
        indexes_dir=indexes_dir,
    )
    engine.migrate()

    # Populate sample data
    job_id = uuid.uuid4()
    now_dt = datetime.now(timezone.utc)
    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme Systems",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    # Save a raw file and DB record
    sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="101")
    abs_raw, h_raw = engine.filestore.save_raw_payload(
        provider=sk.provider,
        board_id=sk.board_id,
        source_posting_id=sk.source_posting_id,
        payload='{"title": "DevOps Engineer"}',
    )
    engine.raw_postings.save_raw_posting(
        RawPosting(
            source_key=sk,
            raw_payload_ref=abs_raw,
            raw_content_hash=h_raw,
            fetch_time=now_dt,
            raw_payload='{"title": "DevOps Engineer"}',
        )
    )

    return engine, data_root, dest_dir


def test_create_backup_success(populated_store: tuple[StorageEngine, Path, Path]) -> None:
    engine, data_root, dest_dir = populated_store
    settings = OperationsSettings()

    manifest, backup_path = create_backup(
        settings=settings,
        data_root=data_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    assert backup_path.exists()
    assert (backup_path / "manifest.json").exists()
    assert (backup_path / "backup.complete").exists()
    assert (backup_path / "database" / "job_automation.db").exists()

    # Verify manifest details
    reloaded = load_manifest(backup_path)
    assert reloaded.backup_id == manifest.backup_id
    assert reloaded.schema_version == engine.get_schema_version()
    assert reloaded.total_files_count >= 2

    # Verification passes
    is_valid, issues = verify_backup(backup_path)
    assert is_valid is True
    assert len(issues) == 0


def test_backup_pruning_respects_keep_count(populated_store: tuple[StorageEngine, Path, Path]) -> None:
    engine, data_root, dest_dir = populated_store
    settings = OperationsSettings(
        backup={"keep_generations": 2, "max_age_days": 1}
    )

    # Create 3 backups
    _, b1 = create_backup(settings=settings, data_root=data_root, engine=engine, destination_override=dest_dir, local_only=True)
    _, b2 = create_backup(settings=settings, data_root=data_root, engine=engine, destination_override=dest_dir, local_only=True)
    _, b3 = create_backup(settings=settings, data_root=data_root, engine=engine, destination_override=dest_dir, local_only=True)

    # Pruning should keep all 3 because none are older than 1 day
    pruned = prune_backups(dest=dest_dir, settings=settings, engine=engine)
    assert pruned == 0
    assert b1.exists()
    assert b2.exists()
    assert b3.exists()

