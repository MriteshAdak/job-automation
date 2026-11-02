"""Tests for GenerationCoordinator Stage 5 delivery integration (GEN-06-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval, DocumentType, GenerationProcessing
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.delivery_service import DeliveryService
from job_automation.generation.delivery_settings import DeliverySettings
from job_automation.generation.records import (
    ArtifactDeliveryRecord,
    FreezeManifest,
    GenerationStage,
    ProjectionIntent,
    ProjectionStatus,
    StageCheckpoint,
    StageStatus,
)
from job_automation.generation.render_records import (
    ArtifactSet,
    RenderedArtifactReceipt,
    compute_file_sha256,
)
from job_automation.generation.settings import GenerationSettings
from job_automation.storage.engine import StorageEngine
from tests.generation.delivery.test_delivery_service import StatefulMockGateway


class MockProjector:
    """Mock projector capturing projected intents."""

    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway
        self.projected_intents: list[ProjectionIntent] = []

    def project_intent(self, intent: ProjectionIntent) -> tuple[bool, ClassifiedError | None]:
        self.projected_intents.append(intent)
        intent.status = ProjectionStatus.ACKNOWLEDGED
        intent.acknowledged_at = datetime.now(timezone.utc)
        return True, None

    def reconcile_intent(self, intent: ProjectionIntent) -> tuple[bool, ClassifiedError | None]:
        return True, None


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    db = tmp_path / "coord_test.sqlite"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db, artifacts_dir=artifacts_dir)
    engine.initialize_schema()
    return engine


def test_coordinator_stage5_delivery_success(storage: StorageEngine, tmp_path: Path) -> None:
    job_id = uuid.uuid4()
    req_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    storage.conn.execute(
        "INSERT INTO canonical_jobs (canonical_job_id, company_name, availability, current_revision_id, first_seen_at, last_seen_at, job_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(job_id), "Siemens AG", "active", "rev1", now.isoformat(), now.isoformat(), "{}", now.isoformat(), now.isoformat()),
    )

    req = GenerationRequest(
        request_id=req_id,
        salesforce_request_id="a01000000000001AAA",
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="content-basic",
        state=GenerationProcessing.UPLOAD_PENDING,
        created_at=now,
        claimed_at=now,
        frozen_input_versions=FrozenInputVersions(
            posting_revision="rev1",
            profile_version="v1",
            policy_version="v1",
            template_version="v1",
        ),
    )
    storage.generation_requests.create_request(req)

    docx_file = tmp_path / f"{req_id}.docx"
    docx_file.write_bytes(b"Simulated DOCX rendered bytes")

    docx_id = uuid.uuid4()
    set_id = uuid.uuid4()
    docx_hash = compute_file_sha256(docx_file)

    docx_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=docx_id,
        artifact_set_id=set_id,
        format="docx",
        version=1,
        content_hash=docx_hash,
        size_bytes=docx_file.stat().st_size,
        local_path=str(docx_file),
        relative_managed_path=f"artifacts/{req_id}/v0001/{docx_id}.docx",
        spec_hash="sha256:" + "1" * 64,
        draft_hash="sha256:" + "2" * 64,
        report_hash="sha256:" + "3" * 64,
        layout_digest="sha256:" + "4" * 64,
        created_at=now,
    )

    art_c14 = Artifact(
        artifact_id=docx_id,
        request_id=req_id,
        artifact_version=1,
        format="docx",
        local_path=str(docx_file),
        content_hash=docx_hash,
        size_bytes=docx_file.stat().st_size,
        remote_file_id=None,
        delivery_status="local_only",
        approval_status=DocumentApproval.DRAFT,
        reconciliation_marker=None,
        created_at=now,
    )

    deliv_slot = ArtifactDeliveryRecord(
        delivery_id=uuid.uuid4(),
        request_id=req_id,
        artifact_format="docx",
        artifact_id=docx_id,
        artifact_hash=docx_hash,
        delivery_status="local_only",
    )
    storage.render_artifacts.save_receipt_and_artifact(docx_rcpt, art_c14, deliv_slot)

    art_set = ArtifactSet(
        set_id=set_id,
        request_id=req_id,
        set_version=1,
        required_formats=["docx"],
        artifacts={"docx": docx_rcpt},
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "5" * 64,
        draft_hash="sha256:" + "6" * 64,
        created_at=now,
    )
    storage.render_artifacts.commit_artifact_set(art_set)

    # Rendering stage is already completed
    storage.generation_work.save_checkpoint(
        StageCheckpoint(
            request_id=req_id,
            stage_name=GenerationStage.RENDERING.value,
            stage_operation_id=f"render:{req_id}",
            status=StageStatus.COMPLETED,
            started_at=now,
            completed_at=now,
        )
    )

    mock_gateway = StatefulMockGateway()
    projector = MockProjector(mock_gateway)
    delivery_service = DeliveryService(storage, mock_gateway)

    coordinator = GenerationCoordinator(
        engine=storage,
        input_service=None,  # type: ignore[arg-type]
        generator=None,  # type: ignore[arg-type]
        validator=None,  # type: ignore[arg-type]
        renderer=None,  # type: ignore[arg-type]
        deliverer=delivery_service,
        projector=projector,  # type: ignore[arg-type]
        settings=GenerationSettings(required_formats=["docx"]),
    )

    ready_req, status, err = coordinator._coordinate_delivery(req)
    assert err is None
    assert status == StageStatus.COMPLETED
    assert ready_req.state == GenerationProcessing.READY_FOR_REVIEW

    # Verify Ready projection intent created and dispatched
    assert len(projector.projected_intents) == 1
    intent = projector.projected_intents[0]
    assert intent.desired_remote_state == "Ready_for_Review"
    assert intent.payload["Status__c"] == "Ready_for_Review"
    assert intent.operation_marker.startswith(f"ready:{req_id}:1:")
    assert intent.projection_revision >= 3


def test_coordinator_stage5_delivery_failure_preserves_upload_pending(
    storage: StorageEngine, tmp_path: Path
) -> None:
    job_id = uuid.uuid4()
    req_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    storage.conn.execute(
        "INSERT INTO canonical_jobs (canonical_job_id, company_name, availability, current_revision_id, first_seen_at, last_seen_at, job_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(job_id), "Siemens AG", "active", "rev1", now.isoformat(), now.isoformat(), "{}", now.isoformat(), now.isoformat()),
    )

    req = GenerationRequest(
        request_id=req_id,
        salesforce_request_id="a01000000000001AAA",
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="content-basic",
        state=GenerationProcessing.UPLOAD_PENDING,
        created_at=now,
        claimed_at=now,
        frozen_input_versions=FrozenInputVersions(
            posting_revision="rev1",
            profile_version="v1",
            policy_version="v1",
            template_version="v1",
        ),
    )
    storage.generation_requests.create_request(req)

    docx_file = tmp_path / f"{req_id}.docx"
    docx_file.write_bytes(b"Simulated DOCX rendered bytes")
    docx_id = uuid.uuid4()
    set_id = uuid.uuid4()
    docx_hash = compute_file_sha256(docx_file)

    docx_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=docx_id,
        artifact_set_id=set_id,
        format="docx",
        version=1,
        content_hash=docx_hash,
        size_bytes=docx_file.stat().st_size,
        local_path=str(docx_file),
        relative_managed_path=f"artifacts/{req_id}/v0001/{docx_id}.docx",
        spec_hash="sha256:" + "1" * 64,
        draft_hash="sha256:" + "2" * 64,
        report_hash="sha256:" + "3" * 64,
        layout_digest="sha256:" + "4" * 64,
        created_at=now,
    )

    art_c14 = Artifact(
        artifact_id=docx_id,
        request_id=req_id,
        artifact_version=1,
        format="docx",
        local_path=str(docx_file),
        content_hash=docx_hash,
        size_bytes=docx_file.stat().st_size,
        remote_file_id=None,
        delivery_status="local_only",
        approval_status=DocumentApproval.DRAFT,
        reconciliation_marker=None,
        created_at=now,
    )

    deliv_slot = ArtifactDeliveryRecord(
        delivery_id=uuid.uuid4(),
        request_id=req_id,
        artifact_format="docx",
        artifact_id=docx_id,
        artifact_hash=docx_hash,
        delivery_status="local_only",
    )
    storage.render_artifacts.save_receipt_and_artifact(docx_rcpt, art_c14, deliv_slot)

    art_set = ArtifactSet(
        set_id=set_id,
        request_id=req_id,
        set_version=1,
        required_formats=["docx"],
        artifacts={"docx": docx_rcpt},
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "5" * 64,
        draft_hash="sha256:" + "6" * 64,
        created_at=now,
    )
    storage.render_artifacts.commit_artifact_set(art_set)

    mock_gateway = StatefulMockGateway()
    # Inject quota failure
    mock_gateway.fail_format = "docx"
    mock_gateway.fail_error = ClassifiedError.from_category(
        ErrorCategory.CAPACITY, "Org storage limit reached"
    )

    projector = MockProjector(mock_gateway)
    delivery_service = DeliveryService(storage, mock_gateway)

    coordinator = GenerationCoordinator(
        engine=storage,
        input_service=None,  # type: ignore[arg-type]
        generator=None,  # type: ignore[arg-type]
        validator=None,  # type: ignore[arg-type]
        renderer=None,  # type: ignore[arg-type]
        deliverer=delivery_service,
        projector=projector,  # type: ignore[arg-type]
        settings=GenerationSettings(required_formats=["docx"]),
    )

    res_req, status, err = coordinator._coordinate_delivery(req)
    assert status == StageStatus.BLOCKED
    assert err is not None
    assert err.category == ErrorCategory.CAPACITY
    # Request state remains UPLOAD_PENDING!
    assert res_req.state == GenerationProcessing.UPLOAD_PENDING
    # Zero ready projections dispatched!
    assert len(projector.projected_intents) == 0
    # Physical file is completely preserved!
    assert docx_file.is_file()
