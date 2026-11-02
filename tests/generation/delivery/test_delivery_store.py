"""Tests for ArtifactDeliveryRepository and Migration 015 persistence (GEN-06-S02)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval
from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliveryAttempt,
    DeliveryIntent,
    DeliverySetReceipt,
    RemoteArtifactMapping,
    build_reconciliation_marker,
)
from job_automation.generation.records import ArtifactDeliveryRecord
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def storage(tmp_path) -> StorageEngine:
    db_path = tmp_path / "test_delivery.sqlite"
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path, artifacts_dir=art_dir)
    engine.initialize_schema()
    return engine


def _insert_test_request(engine: StorageEngine, req_id: uuid.UUID) -> None:
    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc).isoformat()
    engine.conn.execute(
        "INSERT INTO canonical_jobs (canonical_job_id, company_name, availability, current_revision_id, first_seen_at, last_seen_at, job_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(job_id), "Test Corp", "active", "rev1", now, now, "{}", now, now),
    )
    engine.conn.execute(
        "INSERT INTO generation_requests (request_id, canonical_job_id, document_type, target_language, template_id, context_strategy, state, created_at, request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(req_id), str(job_id), "cv", "de", "content-basic", "full_json", "running", now, "{}"),
    )
    engine.conn.commit()


def test_intent_lifecycle_and_uniqueness(storage: StorageEngine) -> None:
    req_id = uuid.uuid4()
    _insert_test_request(storage, req_id)
    art_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    marker = build_reconciliation_marker(req_id, art_id, 1)

    intent = DeliveryIntent(
        intent_id=uuid.uuid4(),
        org_id="00D000000000001EAA",
        salesforce_request_id="a01000000000001AAA",
        canonical_salesforce_id="a00000000000001AAA",
        request_id=req_id,
        artifact_set_id=uuid.uuid4(),
        artifact_id=art_id,
        artifact_version=1,
        artifact_format="docx",
        content_hash="sha256:" + "a" * 64,
        size_bytes=2048,
        local_path="C:/artifacts/test.docx",
        reconciliation_marker=marker,
        status="pending",
        created_at=now,
        updated_at=now,
    )

    # 1. Save intent
    saved = storage.artifact_deliveries.save_intent(intent)
    assert saved.intent_id == intent.intent_id

    # 2. Retrieve by UUID, logical key, and marker
    fetched_by_id = storage.artifact_deliveries.get_intent(intent.intent_id)
    assert fetched_by_id is not None
    assert fetched_by_id.status == "pending"

    fetched_by_key = storage.artifact_deliveries.get_intent_by_logical_key(
        "00D000000000001EAA", req_id, art_id, 1
    )
    assert fetched_by_key is not None
    assert fetched_by_key.intent_id == intent.intent_id

    fetched_by_marker = storage.artifact_deliveries.get_intent_by_marker(
        "00D000000000001EAA", marker
    )
    assert fetched_by_marker is not None
    assert fetched_by_marker.intent_id == intent.intent_id

    # 3. Update status
    storage.artifact_deliveries.update_intent_status(intent.intent_id, "sending")
    updated = storage.artifact_deliveries.get_intent(intent.intent_id)
    assert updated is not None
    assert updated.status == "sending"

    # 4. Attempt logging
    attempt = DeliveryAttempt(
        attempt_id=uuid.uuid4(),
        intent_id=intent.intent_id,
        request_id=req_id,
        attempt_sequence=1,
        operation_kind="upload",
        phase="sending",
        started_at=now,
        status="started",
    )
    storage.artifact_deliveries.record_attempt(attempt)
    attempts = storage.artifact_deliveries.list_attempts_for_intent(intent.intent_id)
    assert len(attempts) == 1
    assert attempts[0].attempt_sequence == 1


def test_atomic_format_delivery_commitment(storage: StorageEngine) -> None:
    req_id = uuid.uuid4()
    _insert_test_request(storage, req_id)
    art_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    marker = build_reconciliation_marker(req_id, art_id, 1)

    intent = DeliveryIntent(
        intent_id=uuid.uuid4(),
        org_id="00D000000000001EAA",
        salesforce_request_id="a01000000000001AAA",
        canonical_salesforce_id="a00000000000001AAA",
        request_id=req_id,
        artifact_set_id=uuid.uuid4(),
        artifact_id=art_id,
        artifact_version=1,
        artifact_format="docx",
        content_hash="sha256:" + "b" * 64,
        size_bytes=4096,
        local_path="C:/artifacts/test.docx",
        reconciliation_marker=marker,
        status="sending",
        created_at=now,
        updated_at=now,
    )
    storage.artifact_deliveries.save_intent(intent)

    mapping = RemoteArtifactMapping(
        mapping_id=uuid.uuid4(),
        intent_id=intent.intent_id,
        request_id=req_id,
        artifact_id=art_id,
        artifact_version=1,
        artifact_format="docx",
        content_hash=intent.content_hash,
        org_id="00D000000000001EAA",
        content_document_id="069000000000001AAA",
        content_version_id="068000000000001AAA",
        marker=marker,
        target_record_id="a01000000000001AAA",
        link_id="06A000000000001AAA",
        acknowledged_at=now,
    )

    access_receipt = AccessibilityReceipt(
        receipt_id=uuid.uuid4(),
        mapping_id=mapping.mapping_id,
        request_id=req_id,
        artifact_id=art_id,
        artifact_version=1,
        artifact_format="docx",
        content_version_id="068000000000001AAA",
        content_document_id="069000000000001AAA",
        target_record_id="a01000000000001AAA",
        verification_method="sharing_policy_check",
        verified_at=now,
    )

    artifact = Artifact(
        artifact_id=art_id,
        request_id=req_id,
        artifact_version=1,
        format="docx",
        local_path=intent.local_path,
        content_hash=intent.content_hash,
        size_bytes=intent.size_bytes,
        delivery_status="local_only",
        approval_status=DocumentApproval.DRAFT,
        created_at=now,
    )

    deliv_slot = ArtifactDeliveryRecord(
        delivery_id=uuid.uuid4(),
        request_id=req_id,
        artifact_format="docx",
        artifact_id=art_id,
        artifact_hash=intent.content_hash,
        delivery_status="local_only",
    )

    # Commit format delivery atomically
    storage.artifact_deliveries.commit_format_delivery(
        intent=intent,
        mapping=mapping,
        access_receipt=access_receipt,
        artifact=artifact,
        delivery_slot=deliv_slot,
    )

    # Assert all tables updated
    updated_intent = storage.artifact_deliveries.get_intent(intent.intent_id)
    assert updated_intent is not None and updated_intent.status == "delivered"

    fetched_mapping = storage.artifact_deliveries.get_remote_mapping(
        "00D000000000001EAA", req_id, art_id, 1
    )
    assert fetched_mapping is not None
    assert fetched_mapping.content_version_id == "068000000000001AAA"

    fetched_access = storage.artifact_deliveries.get_accessibility_receipt(req_id, 1, "docx")
    assert fetched_access is not None
    assert fetched_access.content_document_id == "069000000000001AAA"

    fetched_art = storage.artifacts.get_artifact(art_id)
    assert fetched_art is not None
    assert fetched_art.delivery_status == "delivered"
    assert fetched_art.remote_file_id == "068000000000001AAA"
    assert fetched_art.approval_status == DocumentApproval.DRAFT

    fetched_slot = storage.generation_work.get_delivery_record(req_id, "docx")
    assert fetched_slot is not None
    assert fetched_slot.delivery_status == "delivered"
    assert fetched_slot.remote_file_id == "068000000000001AAA"

