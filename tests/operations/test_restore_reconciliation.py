"""Unit tests for inert restoration and remote reconciliation preparation (OPS-01-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.sync import SyncOperation
from job_automation.operations.backup import create_backup
from job_automation.operations.records import OperationsSettings
from job_automation.operations.remote_recovery import generate_candidate_recovery_package
from job_automation.operations.restore import apply_restore, plan_restore
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine


def test_restoration_is_inert_and_preserves_sync_states(tmp_path: Path) -> None:
    src_root = tmp_path / "src"
    dest_dir = tmp_path / "bak"
    target_root = tmp_path / "tgt"
    src_root.mkdir()
    dest_dir.mkdir()

    engine = StorageEngine(db_path=src_root / "database" / "job_automation.db")
    engine.migrate()

    now_dt = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Inert Restoration Co",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    from job_automation.contracts.enums import AssessmentDisposition, PostingAvailability
    from job_automation.contracts.sync import SyncPayload

    # Enqueue a pending sync operation
    op_id = uuid.uuid4()
    sync_payload = SyncPayload(
        canonical_job_id=job_id,
        job_title="Lead Architect",
        company_name="Inert Restoration Co",
        availability=PostingAvailability.ACTIVE,
        assessment_disposition=AssessmentDisposition.ELIGIBLE,
        assessment_reasons="High score",
        last_evaluated_at=now_dt,
    )
    engine.sync_outbox.enqueue_operation(
        SyncOperation(
            operation_id=op_id,
            canonical_job_id=job_id,
            payload_version="1.0",
            payload_fingerprint="fp1",
            locally_owned_payload=sync_payload,
            attempt_count=0,
        )
    )

    settings = OperationsSettings()
    manifest, backup_path = create_backup(
        settings=settings,
        data_root=src_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    plan = plan_restore(backup_path, target_root, settings)
    result = apply_restore(plan, settings)
    assert result.status.value == "succeeded"

    # Restored store has pending sync intact and was not auto-dispatched
    restored_engine = StorageEngine(db_path=target_root / "database" / "job_automation.db")
    try:
        pending = restored_engine.sync_outbox.get_pending_operations()
        assert len(pending) == 1
        assert pending[0].operation_id == op_id
        assert pending[0].attempt_count == 0

        # Can generate SF-04 candidate recovery package from restored store
        config = SyncMappingConfig(expected_org_id="00D000000000001")
        pkg = generate_candidate_recovery_package(restored_engine, config)
        assert pkg is not None
        assert "recovery_instructions" in pkg
    finally:
        restored_engine.close()
