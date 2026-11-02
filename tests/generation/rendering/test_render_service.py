"""Unit and integration tests for RenderService (GEN-05-S06)."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.draft_content import (
    DraftClaim,
    DraftDocumentV2,
    DraftEntry,
    DraftProvenance,
    DraftSection,
    ProtectedSourceValue,
    SubjectiveBlock,
)
from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.generation import FrozenInputVersions
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.generation.render_service import RenderService
from job_automation.generation.render_settings import RenderingSettings
from job_automation.generation.validation_records import (
    DocumentValidationIssue,
    ValidatedDraftForRendering,
)
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def render_env(tmp_path: Path):
    db_path = tmp_path / "render_test.db"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)
    engine.initialize_schema()
    yield engine
    engine.close()


def create_db_request(engine: StorageEngine, doc_type: str = "cv", lang: str = "de") -> uuid.UUID:
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
        (str(job_id), "Muster GmbH", "active", str(rev_id), now.isoformat(), now.isoformat(), "{}", now.isoformat(), now.isoformat()),
    )
    engine.conn.execute(
        """
        INSERT INTO generation_requests (
            request_id, canonical_job_id, document_type, target_language,
            template_id, context_strategy, state, created_at, request_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(req_id), str(job_id), doc_type, lang, "content-basic", "full_json", "queued", now.isoformat(), "{}"),
    )
    return req_id


from tests.generation.rendering.test_docx_renderer import _build_test_draft


def build_test_draft_v2(
    request_id: uuid.UUID,
    doc_type: DocumentType = DocumentType.CV,
    language: str = "de",
) -> DraftDocumentV2:
    return _build_test_draft(doc_type=doc_type, language=language, request_id=request_id)


def test_render_service_docx_success(render_env: StorageEngine) -> None:
    """Test standard DOCX rendering with layout pinning and atomic promotion."""
    req_id = create_db_request(render_env, doc_type="cv", lang="de")
    draft = build_test_draft_v2(req_id, doc_type=DocumentType.CV, language="de")
    draft_hash = compute_sha256_digest(draft)

    envelope = ValidatedDraftForRendering(
        draft=draft,
        draft_hash=draft_hash,
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "a" * 64,
        binding_hash="sha256:" + "b" * 64,
        content_spec_id="2.0",
        render_decision="allowed_for_review",
        requires_human_review=True,
        review_warnings=[],
    )

    service = RenderService(render_env)
    res = service.render_or_reopen(envelope, requested_formats=["docx"])

    assert res.status == "completed"
    assert res.artifact_set is not None
    assert res.artifact_set.is_complete is True
    assert "docx" in res.artifact_set.artifacts

    rcpt = res.artifact_set.artifacts["docx"]
    assert rcpt.format == "docx"
    assert rcpt.size_bytes > 0
    assert Path(rcpt.local_path).is_file()

    # Verify pinned layout was saved
    pin_file = render_env.artifacts_dir.parent / "pinned_layouts" / str(req_id) / "layout-cv-basic-a4_1.0.0.json"
    assert pin_file.is_file()

    # Verify C14 Artifact record
    art = render_env.artifacts.get_artifact(rcpt.artifact_id)
    assert art is not None
    assert art.delivery_status == "local_only"
    assert art.approval_status == DocumentApproval.DRAFT

    # Verify reopening set verifies file integrity
    reopened = service.reopen_artifact_set(req_id, version=1)
    assert reopened.status == "completed"
    assert reopened.artifact_set is not None


def test_render_service_idempotent_reopen(render_env: StorageEngine) -> None:
    """Test calling render_or_reopen twice reuses the existing verified artifact set."""
    req_id = create_db_request(render_env, doc_type="cv", lang="de")
    draft = build_test_draft_v2(req_id, doc_type=DocumentType.CV, language="de")
    draft_hash = compute_sha256_digest(draft)

    envelope = ValidatedDraftForRendering(
        draft=draft,
        draft_hash=draft_hash,
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "a" * 64,
        binding_hash="sha256:" + "b" * 64,
        content_spec_id="2.0",
        render_decision="allowed_for_review",
        requires_human_review=True,
        review_warnings=[],
    )

    service = RenderService(render_env)
    res1 = service.render_or_reopen(envelope, requested_formats=["docx"])
    assert res1.status == "completed"

    # Second call
    res2 = service.render_or_reopen(envelope, requested_formats=["docx"])
    assert res2.status == "completed"
    assert res2.artifact_set.set_id == res1.artifact_set.set_id
    assert res2.artifact_set.artifacts["docx"].content_hash == res1.artifact_set.artifacts["docx"].content_hash


def test_render_service_blocks_on_fatal_or_unauthorized_gate(render_env: StorageEngine) -> None:
    """Test that fatal warnings or disallowed decision block rendering before any execution."""
    req_id = create_db_request(render_env)
    draft = build_test_draft_v2(req_id)

    # ValidatedDraftForRendering enforces no fatal warnings on init
    with pytest.raises(ValueError):
        ValidatedDraftForRendering(
            draft=draft,
            draft_hash=compute_sha256_digest(draft),
            report_id=uuid.uuid4(),
            report_hash="sha256:" + "a" * 64,
            binding_hash="sha256:" + "b" * 64,
            content_spec_id="2.0",
            render_decision="allowed_for_review",
            review_warnings=[
                DocumentValidationIssue(
                    code="fatal_issue",
                    severity="fatal",
                    message="Fatal error",
                    rule_id="RULE_01",
                )
            ],
        )


def test_render_service_blocks_on_unsupported_language(render_env: StorageEngine) -> None:
    """Test that requesting an unsupported language blocks with layout_unavailable."""
    req_id = create_db_request(render_env, lang="en")
    # Build draft with language that has no compatible layout (e.g. en with content-basic)
    draft = build_test_draft_v2(req_id, language="en")
    envelope = ValidatedDraftForRendering(
        draft=draft,
        draft_hash=compute_sha256_digest(draft),
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "a" * 64,
        binding_hash="sha256:" + "b" * 64,
        content_spec_id="2.0",
        render_decision="allowed_for_review",
        requires_human_review=True,
    )

    # Mock catalog to reject language
    from job_automation.generation.layout_catalog import LayoutCatalog
    empty_catalog = LayoutCatalog(catalog={})
    service = RenderService(render_env, layout_catalog=empty_catalog)
    res = service.render_or_reopen(envelope, requested_formats=["docx"])

    assert res.status == "blocked"
    assert res.error is not None
    assert res.reason_code == "layout_unavailable"


def test_render_service_handles_missing_libreoffice_for_pdf(render_env: StorageEngine) -> None:
    """Test PDF conversion failure when LibreOffice is not installed, preserving DOCX attempt."""
    req_id = create_db_request(render_env)
    draft = build_test_draft_v2(req_id)
    envelope = ValidatedDraftForRendering(
        draft=draft,
        draft_hash=compute_sha256_digest(draft),
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "a" * 64,
        binding_hash="sha256:" + "b" * 64,
        content_spec_id="2.0",
        render_decision="allowed_for_review",
        requires_human_review=True,
    )

    settings = RenderingSettings(libreoffice_path=Path("C:/nonexistent/soffice.com"))
    service = RenderService(render_env, settings=settings)
    res = service.render_or_reopen(envelope, requested_formats=["docx", "pdf"])

    assert res.status == "failed"
    assert res.error is not None
    assert "LibreOffice executable (soffice.com) not found" in res.error.message

    # Verify attempts logged in DB
    intent = render_env.render_artifacts.get_intent_by_request(req_id)
    assert intent is not None
    assert intent.status == "failed"

    attempts = render_env.render_artifacts.list_attempts_for_intent(intent.intent_id)
    assert len(attempts) == 2
    assert attempts[0].format == "docx" and attempts[0].status == "completed"
    assert attempts[1].format == "pdf" and attempts[1].status == "failed"


def test_reopen_artifact_set_detects_corruption(render_env: StorageEngine) -> None:
    """Test that tampering with rendered bytes causes reopen to fail."""
    req_id = create_db_request(render_env)
    draft = build_test_draft_v2(req_id)
    envelope = ValidatedDraftForRendering(
        draft=draft,
        draft_hash=compute_sha256_digest(draft),
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "a" * 64,
        binding_hash="sha256:" + "b" * 64,
        content_spec_id="2.0",
        render_decision="allowed_for_review",
        requires_human_review=True,
    )

    service = RenderService(render_env)
    res = service.render_or_reopen(envelope, requested_formats=["docx"])
    assert res.status == "completed"

    docx_path = Path(res.artifact_set.artifacts["docx"].local_path)
    # Corrupt file
    docx_path.write_bytes(b"corrupted_bytes")

    reopened = service.reopen_artifact_set(req_id, version=1)
    assert reopened.status == "failed"
    assert reopened.error is not None
    assert "byte hash mismatch" in reopened.error.message or "size mismatch" in reopened.error.message
