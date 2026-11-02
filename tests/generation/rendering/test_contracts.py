"""Unit tests for GEN-05 rendering contracts, specifications, and schema exports (GEN-05-S01)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import DocumentType
from job_automation.contracts.errors import ClassifiedError
from job_automation.generation.render_records import (
    ApprovedLayout,
    ArtifactSet,
    LocalRenderResult,
    PageSetup,
    RenderAttempt,
    RenderIntent,
    RenderSpecification,
    RenderedArtifactReceipt,
    TypographySetup,
    canonical_json_dumps,
    compute_sha256_digest,
    export_schemas,
)
from job_automation.generation.render_settings import RenderingSettings


def test_approved_layout_invariants():
    now_utc = datetime.now(timezone.utc)
    layout = ApprovedLayout(
        layout_id="layout-cv-basic-a4",
        layout_version="1.0.0",
        document_type=DocumentType.CV,
        supported_languages=["de", "en"],
        supported_content_specs=["content-basic"],
        page_setup=PageSetup(page_size="A4"),
        typography=TypographySetup(primary_font="Calibri", body_font_size_pt=11.0),
        approved_by="test-approver",
        approved_at=now_utc,
    )
    assert layout.layout_digest.startswith("sha256:")
    assert layout.is_approved is True
    assert layout.typography.body_font_size_pt >= 10.0

    # Minimum body font size invariant
    with pytest.raises(ValidationError):
        TypographySetup(body_font_size_pt=8.0)


def test_render_specification_digest():
    now_utc = datetime.now(timezone.utc)
    spec = RenderSpecification(
        request_id=uuid.uuid4(),
        draft_id=uuid.uuid4(),
        draft_hash="sha256:" + "1" * 64,
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "2" * 64,
        layout_id="layout-cv-basic-a4",
        layout_version="1.0.0",
        layout_digest="sha256:" + "3" * 64,
        requested_formats=["docx", "pdf"],
        created_at=now_utc,
    )
    assert spec.spec_hash.startswith("sha256:")


def test_render_intent_and_attempt():
    now_utc = datetime.now(timezone.utc)
    req_id = uuid.uuid4()
    intent = RenderIntent(
        request_id=req_id,
        logical_key="key-123",
        spec_hash="sha256:" + "4" * 64,
        artifact_version=1,
        target_formats=["docx", "pdf"],
        status="pending",
        created_at=now_utc,
        updated_at=now_utc,
    )
    assert intent.artifact_version == 1

    attempt = RenderAttempt(
        intent_id=intent.intent_id,
        request_id=req_id,
        attempt_number=1,
        format="docx",
        staging_dir="staging/123",
        started_at=now_utc,
    )
    assert attempt.attempt_number == 1
    assert attempt.status == "started"


def test_rendered_artifact_receipt_invariants():
    now_utc = datetime.now(timezone.utc)
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    set_id = uuid.uuid4()

    # Valid docx receipt
    docx_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=art_id,
        artifact_set_id=set_id,
        format="docx",
        version=1,
        content_hash="sha256:" + "a" * 64,
        size_bytes=5000,
        local_path="C:/path/doc.docx",
        relative_managed_path="artifacts/req/v0001/doc.docx",
        spec_hash="sha256:" + "b" * 64,
        draft_hash="sha256:" + "c" * 64,
        report_hash="sha256:" + "d" * 64,
        layout_digest="sha256:" + "e" * 64,
        created_at=now_utc,
    )
    assert docx_rcpt.receipt_hash.startswith("sha256:")

    # Size bytes must be positive
    with pytest.raises(ValidationError):
        RenderedArtifactReceipt(
            request_id=req_id,
            artifact_id=art_id,
            artifact_set_id=set_id,
            format="docx",
            version=1,
            content_hash="sha256:" + "a" * 64,
            size_bytes=0,
            local_path="C:/path/doc.docx",
            relative_managed_path="artifacts/req/v0001/doc.docx",
            spec_hash="sha256:" + "b" * 64,
            draft_hash="sha256:" + "c" * 64,
            report_hash="sha256:" + "d" * 64,
            layout_digest="sha256:" + "e" * 64,
            created_at=now_utc,
        )

    # PDF receipt requires docx reference
    pdf_art_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        RenderedArtifactReceipt(
            request_id=req_id,
            artifact_id=pdf_art_id,
            artifact_set_id=set_id,
            format="pdf",
            version=1,
            content_hash="sha256:" + "f" * 64,
            size_bytes=10000,
            local_path="C:/path/doc.pdf",
            relative_managed_path="artifacts/req/v0001/doc.pdf",
            spec_hash=docx_rcpt.spec_hash,
            draft_hash=docx_rcpt.draft_hash,
            report_hash=docx_rcpt.report_hash,
            layout_digest=docx_rcpt.layout_digest,
            docx_artifact_id=None,  # Missing!
            created_at=now_utc,
        )

    # Valid PDF receipt
    pdf_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=pdf_art_id,
        artifact_set_id=set_id,
        format="pdf",
        version=1,
        content_hash="sha256:" + "f" * 64,
        size_bytes=10000,
        local_path="C:/path/doc.pdf",
        relative_managed_path="artifacts/req/v0001/doc.pdf",
        spec_hash=docx_rcpt.spec_hash,
        draft_hash=docx_rcpt.draft_hash,
        report_hash=docx_rcpt.report_hash,
        layout_digest=docx_rcpt.layout_digest,
        docx_artifact_id=art_id,
        docx_content_hash=docx_rcpt.content_hash,
        created_at=now_utc,
    )
    assert pdf_rcpt.docx_artifact_id == art_id


def test_artifact_set_and_render_result():
    now_utc = datetime.now(timezone.utc)
    req_id = uuid.uuid4()
    set_id = uuid.uuid4()

    docx_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=uuid.uuid4(),
        artifact_set_id=set_id,
        format="docx",
        version=1,
        content_hash="sha256:" + "a" * 64,
        size_bytes=5000,
        local_path="C:/path/doc.docx",
        relative_managed_path="artifacts/req/v0001/doc.docx",
        spec_hash="sha256:" + "b" * 64,
        draft_hash="sha256:" + "c" * 64,
        report_hash="sha256:" + "d" * 64,
        layout_digest="sha256:" + "e" * 64,
        created_at=now_utc,
    )

    pdf_rcpt = RenderedArtifactReceipt(
        request_id=req_id,
        artifact_id=uuid.uuid4(),
        artifact_set_id=set_id,
        format="pdf",
        version=1,
        content_hash="sha256:" + "f" * 64,
        size_bytes=10000,
        local_path="C:/path/doc.pdf",
        relative_managed_path="artifacts/req/v0001/doc.pdf",
        spec_hash=docx_rcpt.spec_hash,
        draft_hash=docx_rcpt.draft_hash,
        report_hash=docx_rcpt.report_hash,
        layout_digest=docx_rcpt.layout_digest,
        docx_artifact_id=docx_rcpt.artifact_id,
        docx_content_hash=docx_rcpt.content_hash,
        created_at=now_utc,
    )

    # Incomplete set (only docx, but requires docx and pdf)
    incomplete_set = ArtifactSet(
        set_id=set_id,
        request_id=req_id,
        set_version=1,
        required_formats=["docx", "pdf"],
        artifacts={"docx": docx_rcpt},
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "d" * 64,
        draft_hash="sha256:" + "c" * 64,
        created_at=now_utc,
    )
    assert incomplete_set.is_complete is False

    # Completed render result requires complete set
    with pytest.raises(ValidationError):
        LocalRenderResult(status="completed", artifact_set=incomplete_set)

    # Complete set
    complete_set = ArtifactSet(
        set_id=set_id,
        request_id=req_id,
        set_version=1,
        required_formats=["docx", "pdf"],
        artifacts={"docx": docx_rcpt, "pdf": pdf_rcpt},
        report_id=uuid.uuid4(),
        report_hash="sha256:" + "d" * 64,
        draft_hash="sha256:" + "c" * 64,
        created_at=now_utc,
    )
    assert complete_set.is_complete is True
    res = LocalRenderResult(status="completed", artifact_set=complete_set)
    assert res.status == "completed"

    # Blocked result requires ClassifiedError
    blocked = LocalRenderResult(
        status="blocked",
        error=ClassifiedError.validation("Render gate blocked"),
        reason_code="gate_blocked",
    )
    assert blocked.status == "blocked"


def test_schema_export_completeness(tmp_path: Path):
    out_dir = tmp_path / "schemas" / "v1"
    exported = export_schemas(out_dir)
    assert len(exported) == 7
    for p in exported:
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "$schema" in data
        assert "$id" in data
