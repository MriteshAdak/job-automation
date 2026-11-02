"""Unit tests for RenderArtifactRepository, migration 014, and storage operations (GEN-05-S05)."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval
from job_automation.contracts.errors import ClassifiedError
from job_automation.generation.records import ArtifactDeliveryRecord
from job_automation.generation.render_records import (
    ArtifactSet,
    RenderAttempt,
    RenderIntent,
    RenderedArtifactReceipt,
    compute_file_sha256,
)
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def test_engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)
    engine.initialize_schema()
    yield engine
    engine.close()


def create_test_request(engine: StorageEngine) -> uuid.UUID:
    now = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    req_id = uuid.uuid4()
    engine.conn.execute(
        """
        INSERT INTO canonical_jobs (
            canonical_job_id, company_name, availability, current_revision_id,
            first_seen_at, last_seen_at, job_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(job_id),
            "Test Corp",
            "active",
            str(rev_id),
            now.isoformat(),
            now.isoformat(),
            "{}",
            now.isoformat(),
            now.isoformat(),
        ),
    )
    engine.conn.execute(
        """
        INSERT INTO generation_requests (
            request_id, canonical_job_id, document_type, target_language,
            template_id, context_strategy, state, created_at, request_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(req_id),
            str(job_id),
            "cv",
            "de",
            "content-basic",
            "full_json",
            "queued",
            now.isoformat(),
            "{}",
        ),
    )
    return req_id


def test_schema_migration_014(test_engine: StorageEngine) -> None:
    """Verify tables for render artifacts exist and schema version is at least 14."""
    assert test_engine.get_schema_version() >= 14
    cursor = test_engine.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert "render_intents" in tables
    assert "render_attempts" in tables
    assert "rendered_artifact_receipts" in tables
    assert "artifact_sets" in tables


def test_intent_lifecycle(test_engine: StorageEngine) -> None:
    """Test intent save, retrieve by logical key and request ID."""
    repo = test_engine.render_artifacts
    req_id = create_test_request(test_engine)
    now_utc = datetime.now(timezone.utc)
    intent = RenderIntent(
        intent_id=uuid.uuid4(),
        request_id=req_id,
        logical_key=f"{req_id}:v0001:docx+pdf",
        spec_hash="sha256:" + "a" * 64,
        artifact_version=1,
        target_formats=["docx", "pdf"],
        status="pending",
        created_at=now_utc,
        updated_at=now_utc,
    )
    saved = repo.save_intent(intent)
    assert saved.logical_key == intent.logical_key

    # Retrieve by request
    by_req = repo.get_intent_by_request(req_id)
    assert by_req is not None
    assert by_req.intent_id == intent.intent_id
    assert by_req.target_formats == ["docx", "pdf"]


def test_attempt_logging(test_engine: StorageEngine) -> None:
    """Test logging an attempt for an intent."""
    repo = test_engine.render_artifacts
    req_id = create_test_request(test_engine)
    now_utc = datetime.now(timezone.utc)
    intent = repo.save_intent(
        RenderIntent(
            intent_id=uuid.uuid4(),
            request_id=req_id,
            logical_key=f"{req_id}:v0001:docx",
            spec_hash="sha256:" + "b" * 64,
            artifact_version=1,
            target_formats=["docx"],
            status="in_progress",
            created_at=now_utc,
            updated_at=now_utc,
        )
    )

    attempt = RenderAttempt(
        attempt_id=uuid.uuid4(),
        intent_id=intent.intent_id,
        request_id=req_id,
        attempt_number=1,
        format="docx",
        staging_dir="C:/temp/staging/attempt1",
        started_at=now_utc,
        completed_at=now_utc,
        status="failed",
        exit_code=1,
        duration_ms=150,
        error_json={"code": "renderer_missing", "message": "LibreOffice not found"},
    )
    repo.record_attempt(attempt)

    attempts = repo.list_attempts_for_intent(intent.intent_id)
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 1
    assert attempts[0].error_json["code"] == "renderer_missing"


def test_compound_receipt_save_and_set_commit(test_engine: StorageEngine, tmp_path: Path) -> None:
    """Test compound save of receipt + artifact + delivery slot, and set commit."""
    repo = test_engine.render_artifacts
    req_id = create_test_request(test_engine)
    now_utc = datetime.now(timezone.utc)
    intent = repo.save_intent(
        RenderIntent(
            intent_id=uuid.uuid4(),
            request_id=req_id,
            logical_key=f"{req_id}:v0001:docx",
            spec_hash="sha256:" + "c" * 64,
            artifact_version=1,
            target_formats=["docx"],
            status="in_progress",
            created_at=now_utc,
            updated_at=now_utc,
        )
    )

    # Create dummy artifact file on disk
    art_file = tmp_path / "artifacts" / str(req_id) / "v0001" / "cv.docx"
    art_file.parent.mkdir(parents=True, exist_ok=True)
    art_content = b"PK\x03\x04test_docx_bytes"
    art_file.write_bytes(art_content)
    art_sha256 = "sha256:" + hashlib.sha256(art_content).hexdigest()

    art_id = uuid.uuid4()
    set_id = uuid.uuid4()
    receipt = RenderedArtifactReceipt(
        receipt_id=uuid.uuid4(),
        request_id=req_id,
        artifact_id=art_id,
        artifact_set_id=set_id,
        format="docx",
        version=1,
        content_hash=art_sha256,
        size_bytes=len(art_content),
        local_path=str(art_file),
        relative_managed_path=f"artifacts/{req_id}/v0001/cv.docx",
        spec_hash="sha256:" + "c" * 64,
        draft_hash="sha256:" + "d" * 64,
        report_hash="sha256:" + "e" * 64,
        layout_digest="sha256:" + "f" * 64,
        output_checks={"verified": True},
        created_at=now_utc,
    )

    artifact_c14 = Artifact(
        artifact_id=art_id,
        request_id=req_id,
        artifact_version=1,
        format="docx",
        local_path=str(art_file),
        content_hash=art_sha256,
        size_bytes=len(art_content),
        remote_file_id=None,
        delivery_status="local_only",
        approval_status=DocumentApproval.DRAFT,
        reconciliation_marker=None,
        created_at=now_utc,
    )

    slot_record = ArtifactDeliveryRecord(
        delivery_id=uuid.uuid4(),
        request_id=req_id,
        artifact_format="docx",
        artifact_id=art_id,
        artifact_hash=art_sha256,
        remote_file_id=None,
        delivery_status="local_only",
        delivered_at=None,
        receipt_data={},
    )

    # Save compound receipt
    repo.save_receipt_and_artifact(receipt, artifact_c14, slot_record)

    # Verify rows in rendered_artifact_receipts and artifacts
    receipts = repo.get_receipts_by_request(req_id, version=1)
    assert len(receipts) == 1
    assert receipts[0].content_hash == art_sha256
    assert receipts[0].format == "docx"

    art_row = test_engine.artifacts.get_artifact(art_id)
    assert art_row is not None
    assert art_row.delivery_status == "local_only"
    assert art_row.approval_status == DocumentApproval.DRAFT

    # Commit artifact set
    set_record = ArtifactSet(
        set_id=set_id,
        request_id=req_id,
        set_version=1,
        required_formats=["docx"],
        artifacts={"docx": receipt},
        is_complete=True,
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "e" * 64,
        draft_hash="sha256:" + "d" * 64,
        set_hash="sha256:" + "1" * 64,
        created_at=now_utc,
    )
    repo.commit_artifact_set(set_record)

    committed = repo.get_artifact_set(req_id, version=1)
    assert committed is not None
    assert committed.is_complete is True
    assert "docx" in committed.artifacts

    # Reopen and verify against disk
    reopened, err = repo.reopen_and_verify_set(req_id, version=1)
    assert err is None
    assert reopened is not None
    assert reopened.set_id == set_record.set_id


def test_reopen_and_verify_detects_tampered_or_missing_file(
    test_engine: StorageEngine, tmp_path: Path
) -> None:
    """Verify reopening reports ClassifiedError when file on disk is altered or deleted."""
    repo = test_engine.render_artifacts
    req_id = create_test_request(test_engine)
    now_utc = datetime.now(timezone.utc)

    art_file = tmp_path / "artifacts" / str(req_id) / "v0001" / "letter.docx"
    art_file.parent.mkdir(parents=True, exist_ok=True)
    content = b"original_docx_content"
    art_file.write_bytes(content)
    art_sha256 = "sha256:" + hashlib.sha256(content).hexdigest()

    art_id = uuid.uuid4()
    set_id = uuid.uuid4()
    receipt = RenderedArtifactReceipt(
        receipt_id=uuid.uuid4(),
        request_id=req_id,
        artifact_id=art_id,
        artifact_set_id=set_id,
        format="docx",
        version=1,
        content_hash=art_sha256,
        size_bytes=len(content),
        local_path=str(art_file),
        relative_managed_path=f"artifacts/{req_id}/v0001/letter.docx",
        spec_hash="sha256:" + "c" * 64,
        draft_hash="sha256:" + "d" * 64,
        report_hash="sha256:" + "e" * 64,
        layout_digest="sha256:" + "f" * 64,
        output_checks={"verified": True},
        created_at=now_utc,
    )

    artifact_c14 = Artifact(
        artifact_id=art_id,
        request_id=req_id,
        artifact_version=1,
        format="docx",
        local_path=str(art_file),
        content_hash=art_sha256,
        size_bytes=len(content),
        delivery_status="local_only",
        approval_status=DocumentApproval.DRAFT,
        created_at=now_utc,
    )

    slot_record = ArtifactDeliveryRecord(
        delivery_id=uuid.uuid4(),
        request_id=req_id,
        artifact_format="docx",
        artifact_id=art_id,
        artifact_hash=art_sha256,
        delivery_status="local_only",
    )
    repo.save_receipt_and_artifact(receipt, artifact_c14, slot_record)

    set_record = ArtifactSet(
        set_id=set_id,
        request_id=req_id,
        set_version=1,
        required_formats=["docx"],
        artifacts={"docx": receipt},
        is_complete=True,
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "e" * 64,
        draft_hash="sha256:" + "d" * 64,
        set_hash="sha256:" + "2" * 64,
        created_at=now_utc,
    )
    repo.commit_artifact_set(set_record)

    # 1. Tamper with the file
    art_file.write_bytes(b"tampered_content_bytes")
    reopened, err = repo.reopen_and_verify_set(req_id, version=1)
    assert reopened is None
    assert err is not None
    assert "size mismatch" in err.message or "byte hash mismatch" in err.message

    # 2. Delete the file
    art_file.unlink()
    reopened, err = repo.reopen_and_verify_set(req_id, version=1)
    assert reopened is None
    assert err is not None
    assert "missing on disk" in err.message
