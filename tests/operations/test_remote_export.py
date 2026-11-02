"""Unit tests for remote Salesforce recovery export assembly (OPS-01-S05)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.operations.records import RemoteCompleteness
from job_automation.operations.remote_export import assemble_remote_export
from job_automation.salesforce.sync_records import CandidateFieldSnapshot
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def mock_storage(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()
    return engine


def test_assemble_remote_export_without_config(mock_storage: StorageEngine) -> None:
    export = assemble_remote_export(mock_storage, config=None)
    assert export.completeness_status == RemoteCompleteness.LOCAL_ONLY_ABSENT_SF04
    assert "SF-04" in export.notes


def test_assemble_remote_export_complete(mock_storage: StorageEngine) -> None:
    job_id = uuid.uuid4()
    now_dt = datetime.now(timezone.utc)

    # 1. Add canonical job
    mock_storage.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    # 2. Add candidate snapshot
    mock_storage.candidate_snapshots.save_snapshot(
        CandidateFieldSnapshot(
            snapshot_id=uuid.uuid4(),
            org_id="00D000000000001",
            canonical_job_id=job_id,
            remote_record_id="a000001",
            mapping_version="1.0",
            snapshot_hash="sha256:111",
            candidate_fields={
                "Candidate_Notes__c": "Spoke with recruiter; follow-up next Tuesday",
                "Application_Progress__c": "Screening",
            },
            source_modification_token="2026-10-29T10:00:00Z",
            observed_at=now_dt,
            created_at=now_dt,
        )
    )

    # Save complete checkpoint
    mock_storage.candidate_snapshots.save_checkpoint(
        checkpoint_id="cp-1",
        org_id="00D000000000001",
        last_processed_key="a000001",
        is_complete=True,
        records_processed=1,
    )

    config = SyncMappingConfig(
        expected_org_id="00D000000000001",
        candidate_fields=["Candidate_Notes__c", "Application_Progress__c"],
    )

    export = assemble_remote_export(mock_storage, config=config)
    assert export.completeness_status == RemoteCompleteness.COMPLETE
    assert export.saved_count == 1
    assert export.expected_count == 1
    assert export.checksum != ""
    assert str(job_id) in export.per_record_tokens

