"""Integration tests for DeliveryService end-to-end delivery, partial failures, and quota preservation (GEN-06-S04, S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.salesforce import GatewayFailure, GatewayResult, OperationKind, RecoveryAction, RemoteOutcome
from job_automation.generation.delivery_records import (
    DeliverySetReceipt,
    RemoteArtifactMapping,
    build_reconciliation_marker,
)
from job_automation.generation.delivery_service import DeliveryService
from job_automation.generation.delivery_settings import DeliverySettings
from job_automation.generation.render_records import (
    ArtifactSet,
    RenderedArtifactReceipt,
    compute_file_sha256,
)
from job_automation.salesforce.file_records import (
    ContentDocumentLinkMetadata,
    ContentVersionMetadata,
    CreateContentDocumentLinkRequest,
    CreateContentDocumentLinkResult,
    CreateContentVersionRequest,
    CreateContentVersionResult,
)
from job_automation.storage.engine import StorageEngine


class StatefulMockGateway:
    """Mock gateway that tracks uploaded files, handles quota failure injection, and supports queries."""

    def __init__(self) -> None:
        self.versions: dict[str, ContentVersionMetadata] = {}  # version_id -> metadata
        self.marker_index: dict[str, list[ContentVersionMetadata]] = {}
        self.links: list[ContentDocumentLinkMetadata] = []
        self.upload_calls: list[CreateContentVersionRequest] = []
        self.fail_format: str | None = None
        self.fail_error: ClassifiedError | None = None

    def create_content_version(
        self, request: CreateContentVersionRequest
    ) -> GatewayResult[CreateContentVersionResult]:
        self.upload_calls.append(request)

        # Check if error injected
        if self.fail_format and self.fail_format in request.path_on_client:
            fail = GatewayFailure(
                error=self.fail_error or ClassifiedError.from_category(ErrorCategory.CAPACITY, "Storage limit reached"),
                safe_provider_code="STORAGE_LIMIT_EXCEEDED",
                operation_kind=OperationKind.UPDATE_RECORD,
                remote_outcome=RemoteOutcome.REJECTED,
                recovery_action=RecoveryAction.FIX_CONFIGURATION,
            )
            return GatewayResult.fail(fail)

        v_id = f"068{uuid.uuid4().hex[:15]}"
        d_id = f"069{uuid.uuid4().hex[:15]}"
        rec = ContentVersionMetadata(
            content_version_id=v_id,
            content_document_id=d_id,
            title=request.title,
            path_on_client=request.path_on_client,
            content_size=len(request.version_data),
            reconciliation_marker=request.reconciliation_marker,
        )
        self.versions[v_id] = rec
        self.marker_index.setdefault(request.reconciliation_marker, []).append(rec)
        return GatewayResult.success(
            CreateContentVersionResult(
                content_version_id=v_id,
                content_document_id=d_id,
                reconciliation_marker=request.reconciliation_marker,
            )
        )

    def get_content_version(self, version_id: str) -> GatewayResult[ContentVersionMetadata]:
        if version_id in self.versions:
            return GatewayResult.success(self.versions[version_id])
        return GatewayResult.fail(
            GatewayFailure(
                error=ClassifiedError.validation("Version not found"),
                operation_kind=OperationKind.GET_RECORD,
                remote_outcome=RemoteOutcome.NOT_SENT,
                recovery_action=RecoveryAction.NONE,
            )
        )

    def query_content_versions_by_marker(
        self, marker: str
    ) -> GatewayResult[list[ContentVersionMetadata]]:
        recs = self.marker_index.get(marker, [])
        return GatewayResult.success(recs)

    def create_content_document_link(
        self, request: CreateContentDocumentLinkRequest
    ) -> GatewayResult[CreateContentDocumentLinkResult]:
        link = ContentDocumentLinkMetadata(
            link_id=f"06A{uuid.uuid4().hex[:15]}",
            content_document_id=request.content_document_id,
            linked_entity_id=request.linked_entity_id,
            share_type=request.share_type,
            visibility=request.visibility,
        )
        self.links.append(link)
        return GatewayResult.success(
            CreateContentDocumentLinkResult(
                link_id=link.link_id,
                content_document_id=request.content_document_id,
                linked_entity_id=request.linked_entity_id,
                share_type=request.share_type,
                visibility=request.visibility,
            )
        )

    def query_content_document_links(
        self, content_document_id: str, linked_entity_id: str | None = None
    ) -> GatewayResult[list[ContentDocumentLinkMetadata]]:
        matched = [
            l
            for l in self.links
            if l.content_document_id == content_document_id
            and (linked_entity_id is None or l.linked_entity_id == linked_entity_id)
        ]
        return GatewayResult.success(matched)

    def download_content_version_bytes(
        self, version_id: str, max_bytes: int = 10485760
    ) -> GatewayResult[bytes]:
        return GatewayResult.success(b"mock_bytes")


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    db = tmp_path / "test.sqlite"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db, artifacts_dir=artifacts_dir)
    engine.initialize_schema()
    return engine


def _setup_test_environment(
    storage: StorageEngine, tmp_path: Path
) -> tuple[GenerationRequest, ArtifactSet]:
    req_id = uuid.uuid4()
    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    storage.conn.execute(
        "INSERT INTO canonical_jobs (canonical_job_id, company_name, availability, current_revision_id, first_seen_at, last_seen_at, job_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(job_id), "Test AG", "active", "rev1", now.isoformat(), now.isoformat(), "{}", now.isoformat(), now.isoformat()),
    )
    req = GenerationRequest(
        request_id=req_id,
        salesforce_request_id="a01000000000001AAA",
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="content-basic",
        created_at=now,
    )
    storage.generation_requests.create_request(req)

    # Create dummy local files
    docx_file = tmp_path / "cv.docx"
    docx_file.write_bytes(b"DOCX content bytes for testing")
    pdf_file = tmp_path / "cv.pdf"
    pdf_file.write_bytes(b"PDF content bytes for testing")

    docx_id = uuid.uuid4()
    pdf_id = uuid.uuid4()
    set_id = uuid.uuid4()

    docx_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=docx_id,
        artifact_set_id=set_id,
        format="docx",
        version=1,
        content_hash=compute_file_sha256(docx_file),
        size_bytes=docx_file.stat().st_size,
        local_path=str(docx_file),
        relative_managed_path=f"artifacts/{req_id}/v0001/{docx_id}.docx",
        spec_hash="sha256:" + "1" * 64,
        draft_hash="sha256:" + "2" * 64,
        report_hash="sha256:" + "3" * 64,
        layout_digest="sha256:" + "4" * 64,
        created_at=now,
    )

    pdf_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=pdf_id,
        artifact_set_id=set_id,
        format="pdf",
        version=1,
        content_hash=compute_file_sha256(pdf_file),
        size_bytes=pdf_file.stat().st_size,
        local_path=str(pdf_file),
        relative_managed_path=f"artifacts/{req_id}/v0001/{pdf_id}.pdf",
        spec_hash="sha256:" + "1" * 64,
        draft_hash="sha256:" + "2" * 64,
        report_hash="sha256:" + "3" * 64,
        layout_digest="sha256:" + "4" * 64,
        docx_artifact_id=docx_id,
        docx_content_hash=docx_rcpt.content_hash,
        created_at=now,
    )

    art_set = ArtifactSet(
        set_id=set_id,
        request_id=req_id,
        set_version=1,
        required_formats=["docx", "pdf"],
        artifacts={"docx": docx_rcpt, "pdf": pdf_rcpt},
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "5" * 64,
        draft_hash="sha256:" + "6" * 64,
        created_at=now,
    )
    return req, art_set


def test_deliver_or_reconcile_happy_path(storage: StorageEngine, tmp_path: Path) -> None:
    req, art_set = _setup_test_environment(storage, tmp_path)
    gateway = StatefulMockGateway()
    settings = DeliverySettings(access_verification_method="sharing_policy_check")
    service = DeliveryService(storage, gateway, settings)

    set_receipt, err = service.deliver_or_reconcile(
        request=req,
        artifact_set=art_set,
        salesforce_request_id=req.salesforce_request_id or "",
        canonical_salesforce_id="a00000000000001AAA",
    )

    assert err is None
    assert set_receipt is not None
    assert set_receipt.is_accessible is True
    assert len(set_receipt.mappings) == 2
    assert "docx" in set_receipt.mappings and "pdf" in set_receipt.mappings
    assert len(gateway.upload_calls) == 2

    # Verify storage artifacts updated to delivered
    docx_id = art_set.artifacts["docx"].artifact_id
    pdf_id = art_set.artifacts["pdf"].artifact_id
    docx_art = storage.artifacts.get_artifact(docx_id)
    pdf_art = storage.artifacts.get_artifact(pdf_id)
    assert docx_art is not None and docx_art.delivery_status == "delivered"
    assert pdf_art is not None and pdf_art.delivery_status == "delivered"
    assert docx_art.approval_status == DocumentApproval.DRAFT
    assert pdf_art.approval_status == DocumentApproval.DRAFT


def test_partial_failure_preserves_upload_pending_and_resumes_cleanly(
    storage: StorageEngine, tmp_path: Path
) -> None:
    req, art_set = _setup_test_environment(storage, tmp_path)
    gateway = StatefulMockGateway()
    # Inject quota failure on PDF
    gateway.fail_format = "pdf"
    gateway.fail_error = ClassifiedError.from_category(
        ErrorCategory.CAPACITY, "Salesforce storage quota exceeded"
    )

    settings = DeliverySettings(access_verification_method="sharing_policy_check")
    service = DeliveryService(storage, gateway, settings)

    # 1. First execution: DOCX succeeds, PDF fails
    set_receipt, err = service.deliver_or_reconcile(
        request=req,
        artifact_set=art_set,
        salesforce_request_id=req.salesforce_request_id or "",
        canonical_salesforce_id="a00000000000001AAA",
    )
    assert set_receipt is None
    assert err is not None
    assert err.category == ErrorCategory.CAPACITY
    assert len(gateway.upload_calls) == 2  # Attempted DOCX (ok) and PDF (failed)

    # Verify DOCX is committed as delivered, while PDF is not
    docx_id = art_set.artifacts["docx"].artifact_id
    docx_mapping = storage.artifact_deliveries.get_remote_mapping(
        settings.expected_org_id, req.request_id, docx_id, 1
    )
    assert docx_mapping is not None
    assert docx_mapping.content_version_id != ""

    # Verify both physical files remain on disk
    assert Path(art_set.artifacts["docx"].local_path).is_file()
    assert Path(art_set.artifacts["pdf"].local_path).is_file()

    # 2. Quota remediated; worker retries!
    gateway.fail_format = None
    gateway.upload_calls.clear()

    retry_receipt, retry_err = service.deliver_or_reconcile(
        request=req,
        artifact_set=art_set,
        salesforce_request_id=req.salesforce_request_id or "",
        canonical_salesforce_id="a00000000000001AAA",
    )
    assert retry_err is None
    assert retry_receipt is not None
    assert retry_receipt.is_accessible is True

    # Critical check: DOCX was ALREADY delivered and NOT re-uploaded! Only PDF was uploaded!
    assert len(gateway.upload_calls) == 1
    assert "pdf" in gateway.upload_calls[0].path_on_client
