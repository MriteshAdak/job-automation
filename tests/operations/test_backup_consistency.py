"""Unit tests for WAL consistency and maintenance worker exclusion during backup (OPS-01-S06)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.operations.backup import create_backup
from job_automation.operations.records import OperationsSettings
from job_automation.orchestration.errors import LockContentionError
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine


def test_backup_captures_committed_wal_data(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    dest_dir = tmp_path / "backup"
    dest_dir.mkdir()

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
    )
    engine.migrate()

    job_id = uuid.uuid4()
    now_dt = datetime.now(timezone.utc)

    # Commit data to WAL
    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Committed In WAL Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    # Perform backup
    settings = OperationsSettings()
    manifest, backup_dir = create_backup(
        settings=settings,
        data_root=data_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    # Inspect backup database directly in isolation
    backup_db = backup_dir / "database" / "job_automation.db"
    conn = sqlite3.connect(str(backup_db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT company_name FROM canonical_jobs WHERE canonical_job_id = ?", (str(job_id),))
        row = cur.fetchone()
        assert row is not None
        assert row["company_name"] == "Committed In WAL Corp"
    finally:
        conn.close()


def test_maintenance_lock_excludes_search_workers(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "database").mkdir()

    lock = WindowsWorkerLock(data_root)

    # Acquire lock as MAINTENANCE
    with lock.acquire(owner_kind=OwnerKind.MAINTENANCE):
        # A concurrent worker attempting to acquire SEARCH must raise LockContentionError
        worker_lock = WindowsWorkerLock(data_root)
        with pytest.raises(LockContentionError, match="Concurrent execution"):
            worker_lock.acquire_lock(owner_kind=OwnerKind.SEARCH, timeout_seconds=0.01)

