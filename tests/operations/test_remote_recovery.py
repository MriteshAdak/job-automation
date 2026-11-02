"""Unit tests for candidate-owned Salesforce recovery package and conflict handling (OPS-01-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.operations.remote_recovery import (
    generate_candidate_recovery_package,
    reconcile_recovery_conflicts,
)
from job_automation.salesforce.sync_records import CandidateFieldSnapshot
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def storage_with_snapshots(tmp_path: Path) -> tuple[StorageEngine, uuid.UUID]:
    db_path = tmp_path / "test.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    job_id = uuid.uuid4()
    now_dt = datetime.now(timezone.utc)

    from job_automation.contracts.identity import CanonicalJob
    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    engine.candidate_snapshots.save_snapshot(
        CandidateFieldSnapshot(
            snapshot_id=uuid.uuid4(),
            org_id="00D000000000001",
            canonical_job_id=job_id,
            remote_record_id="a000001",
            mapping_version="1.0",
            snapshot_hash="sha256:111",
            candidate_fields={
                "Candidate_Notes__c": "Interview scheduled for Friday (Prüfung)",
                "Follow_Up_Date__c": "2026-11-05",
                "Candidate_Decision__c": None,  # Explicit null
            },
            source_modification_token="2026-10-29T10:00:00Z",
            observed_at=now_dt,
            created_at=now_dt,
        )
    )
    return engine, job_id


def test_recovery_package_same_vs_replacement_org(
    storage_with_snapshots: tuple[StorageEngine, uuid.UUID],
) -> None:
    engine, job_id = storage_with_snapshots
    config = SyncMappingConfig(expected_org_id="00D000000000001")

    # Same org package
    pkg_same = generate_candidate_recovery_package(engine, config)
    assert pkg_same["is_replacement_org"] is False
    assert pkg_same["records"][0]["remote_record_id"] == "a000001"
    assert pkg_same["records"][0]["candidate_fields"]["Candidate_Decision__c"] is None

    # Replacement org package
    pkg_repl = generate_candidate_recovery_package(engine, config, target_org_id="00D999999999999")
    assert pkg_repl["is_replacement_org"] is True
    assert pkg_repl["records"][0]["remote_record_id"] is None


def test_reconcile_recovery_conflicts_newer_remote_edit_wins(
    storage_with_snapshots: tuple[StorageEngine, uuid.UUID],
) -> None:
    engine, job_id = storage_with_snapshots
    config = SyncMappingConfig(expected_org_id="00D000000000001")
    pkg = generate_candidate_recovery_package(engine, config)

    # Simulate live Salesforce where candidate updated notes *after* the backup cut
    live_remote = {
        str(job_id): {
            "Id": "a000001",
            "SystemModstamp": "2026-10-29T12:00:00Z",  # Newer than 10:00:00Z
            "Candidate_Notes__c": "Candidate updated notes directly in Salesforce UI",
            "Follow_Up_Date__c": "2026-11-10",
        }
    }

    report = reconcile_recovery_conflicts(pkg, live_remote)

    assert report["conflicts_retained_remote"] == 1
    assert report["records_to_restore"] == 0
    assert report["conflict_details"][0]["canonical_job_id"] == str(job_id)
    assert report["conflict_details"][0]["resolution"] == "retain_newer_remote_edit"
