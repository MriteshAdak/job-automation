"""Unit tests for isolated restore planning and execution (OPS-01-S07)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.operations.backup import create_backup
from job_automation.operations.records import OperationStatus, OperationsSettings
from job_automation.operations.restore import apply_restore, plan_restore
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def source_environment(tmp_path: Path) -> tuple[StorageEngine, Path, Path]:
    src_root = tmp_path / "Source Data Root Prüfung ä"
    src_root.mkdir()
    dest_dir = tmp_path / "Backups"
    dest_dir.mkdir()

    engine = StorageEngine(
        db_path=src_root / "database" / "job_automation.db",
        raw_dir=src_root / "raw",
        artifacts_dir=src_root / "artifacts",
    )
    engine.migrate()

    now_dt = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Cloud Solutions GmbH",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    # Save a raw file
    sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="101")
    abs_raw, h_raw = engine.filestore.save_raw_payload(
        provider=sk.provider,
        board_id=sk.board_id,
        source_posting_id=sk.source_posting_id,
        payload='{"title": "Lead Software Engineer"}',
    )
    engine.raw_postings.save_raw_posting(
        RawPosting(
            source_key=sk,
            raw_payload_ref=abs_raw,
            raw_content_hash=h_raw,
            fetch_time=now_dt,
            raw_payload='{"title": "Lead Software Engineer"}',
        )
    )

    return engine, src_root, dest_dir


def test_restore_into_isolated_target(
    source_environment: tuple[StorageEngine, Path, Path], tmp_path: Path
) -> None:
    engine, src_root, dest_dir = source_environment
    settings = OperationsSettings()

    # 1. Take backup
    manifest, backup_path = create_backup(
        settings=settings,
        data_root=src_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    # 2. Target restore root (isolated, spaces, unicode)
    target_root = tmp_path / "Restored Deployment Prüfung ö"

    # 3. Plan restore
    plan = plan_restore(backup_path, target_root, settings)
    assert plan.is_valid is True
    assert plan.files_to_restore >= 2

    # 4. Apply restore
    result = apply_restore(plan, settings)
    assert result.status == OperationStatus.SUCCEEDED
    assert result.integrity_check_passed is True
    assert result.foreign_key_check_passed is True
    assert result.relocated_paths_count >= 1

    # 5. Verify target engine reads restored data with relocated paths
    restored_engine = StorageEngine(
        db_path=target_root / "database" / "job_automation.db",
        raw_dir=target_root / "raw",
    )
    try:
        sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="101")
        post = restored_engine.raw_postings.get_raw_posting(sk)
        assert post is not None
        # Path must be relocated to target_root!
        assert str(target_root) in post.raw_payload_ref
        assert str(src_root) not in post.raw_payload_ref
        # Content at relocated path must exist and match
        assert Path(post.raw_payload_ref).is_file()
    finally:
        restored_engine.close()

