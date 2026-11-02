"""Unit tests for cross-record link preservation across restore (OPS-01-S07)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval, DocumentType, GenerationProcessing
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.sync import SyncOperation
from job_automation.operations.backup import create_backup
from job_automation.operations.records import OperationsSettings
from job_automation.operations.restore import apply_restore, plan_restore
from job_automation.storage.engine import StorageEngine


def test_restore_preserves_cross_record_relationships(tmp_path: Path) -> None:
    src_root = tmp_path / "source_root"
    src_root.mkdir()
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    target_root = tmp_path / "target_root"

    engine = StorageEngine(
        db_path=src_root / "database" / "job_automation.db",
        raw_dir=src_root / "raw",
        artifacts_dir=src_root / "artifacts",
    )
    engine.migrate()

    now_dt = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    op_id = uuid.uuid4()

    # 1. Canonical job
    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Enterprise Networks AG",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    # 2. Generation request
    engine.generation_requests.create_request(
        GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="cv_standard",
            created_at=now_dt,
            state=GenerationProcessing.READY_FOR_REVIEW,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1",
                profile_version="1",
                policy_version="1",
                template_version="1",
            ),
        )
    )

    # 3. Artifact
    art_path, art_hash, art_size = engine.filestore.save_artifact_file(
        request_id=req_id,
        filename="Lebenslauf.pdf",
        content=b"%PDF-1.4 sample content",
    )
    engine.artifacts.save_artifact(
        Artifact(
            artifact_id=art_id,
            request_id=req_id,
            format="pdf",
            local_path=art_path,
            content_hash=art_hash,
            size_bytes=art_size,
            delivery_status="local_only",
            approval_status=DocumentApproval.DRAFT,
            created_at=now_dt,
        )
    )

    # 4. Sync Operation
    from job_automation.contracts.enums import AssessmentDisposition, PostingAvailability
    from job_automation.contracts.sync import SyncPayload

    sync_payload = SyncPayload(
        canonical_job_id=job_id,
        job_title="Lead Architect",
        company_name="Enterprise Networks AG",
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
            payload_fingerprint="fp123",
            locally_owned_payload=sync_payload,
            attempt_count=0,
        )
    )

    # 5. Backup
    settings = OperationsSettings()
    manifest, backup_path = create_backup(
        settings=settings,
        data_root=src_root,
        engine=engine,
        destination_override=dest_dir,
        local_only=True,
    )

    # 6. Restore to target root
    plan = plan_restore(backup_path, target_root, settings)
    result = apply_restore(plan, settings)
    assert result.status.value == "succeeded"

    # 7. Verify links in restored data
    restored_engine = StorageEngine(
        db_path=target_root / "database" / "job_automation.db",
        raw_dir=target_root / "raw",
        artifacts_dir=target_root / "artifacts",
    )
    try:
        # Check canonical job
        c_job = restored_engine.canonical_jobs.get_canonical_job(job_id)
        assert c_job is not None
        assert c_job.company_name == "Enterprise Networks AG"

        # Check generation request linked to job
        req = restored_engine.generation_requests.get_request(req_id)
        assert req is not None
        assert req.canonical_job_id == job_id

        # Check artifact linked to request
        art = restored_engine.artifacts.get_artifact(art_id)
        assert art is not None
        assert art.request_id == req_id
        # Path relocated to target_root
        assert str(target_root) in art.local_path
        assert Path(art.local_path).is_file()
        assert Path(art.local_path).read_bytes() == b"%PDF-1.4 sample content"

        # Check sync operation
        pending = restored_engine.sync_outbox.get_pending_operations()
        assert any(op.operation_id == op_id for op in pending)
    finally:
        restored_engine.close()
