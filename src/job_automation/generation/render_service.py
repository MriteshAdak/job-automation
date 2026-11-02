"""Durable rendering service coordinating layout catalog, DOCX/PDF generation, and atomic promotion (GEN-05-S06)."""
from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.docx_renderer import DocxRenderer
from job_automation.generation.layout_catalog import LayoutCatalog
from job_automation.generation.libreoffice_converter import LibreOfficeConverter
from job_automation.generation.records import ArtifactDeliveryRecord
from job_automation.generation.render_ports import DocumentRendererServicePort
from job_automation.generation.render_records import (
    ApprovedLayout,
    ArtifactSet,
    LocalRenderResult,
    RenderAttempt,
    RenderIntent,
    RenderSpecification,
    RenderedArtifactReceipt,
    compute_file_sha256,
)
from job_automation.generation.render_settings import RenderingSettings
from job_automation.generation.validation_records import ValidatedDraftForRendering
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class RenderService(DocumentRendererServicePort):
    """Orchestrates layout catalog pinning, staged execution, verification, and atomic publication."""

    def __init__(
        self,
        engine: StorageEngine,
        settings: RenderingSettings | None = None,
        layout_catalog: LayoutCatalog | None = None,
        docx_renderer: DocxRenderer | None = None,
        pdf_converter: LibreOfficeConverter | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings or RenderingSettings()
        self.layout_catalog = layout_catalog or LayoutCatalog()
        self.docx_renderer = docx_renderer or DocxRenderer()
        self.pdf_converter = pdf_converter or LibreOfficeConverter(self.settings)

    def reopen_artifact_set(
        self,
        request_id: uuid.UUID,
        version: int = 1,
    ) -> LocalRenderResult:
        """Reopen and verify all saved artifacts for a request without re-rendering."""
        artifact_set, err = self.engine.render_artifacts.reopen_and_verify_set(
            request_id=request_id,
            version=version,
        )
        if err is not None:
            return LocalRenderResult(
                status="failed",
                error=err,
                reason_code="disk_verification_failed",
            )
        if artifact_set is None:
            return LocalRenderResult(
                status="failed",
                error=ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"No complete artifact set found for request {request_id} version {version}",
                    details={"code": "artifact_set_not_found"},
                ),
                reason_code="artifact_set_not_found",
            )
        return LocalRenderResult(
            status="completed",
            artifact_set=artifact_set,
        )

    def render_or_reopen(
        self,
        validated_draft: ValidatedDraftForRendering,
        requested_formats: list[str] | None = None,
    ) -> LocalRenderResult:
        """Render a validated draft or reopen existing immutable saved artifacts."""
        draft = validated_draft.draft
        request_id = draft.request_id

        # 1. Validation gate authorization check
        if validated_draft.render_decision != "allowed_for_review":
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Rendering blocked by validation decision: '{validated_draft.render_decision}'",
                details={"code": "render_decision_forbidden"},
            )
            return LocalRenderResult(status="blocked", error=err, reason_code="render_decision_forbidden")

        if any(w.severity == "fatal" for w in validated_draft.review_warnings):
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="Rendering blocked: validated draft envelope contains fatal issues",
                details={"code": "fatal_issues_present"},
            )
            return LocalRenderResult(status="blocked", error=err, reason_code="fatal_issues_present")

        # 2. Determine target formats
        raw_formats = requested_formats or self.settings.default_formats
        target_formats: list[Literal["docx", "pdf"]] = []
        for fmt in raw_formats:
            fmt_lower = fmt.lower()
            if fmt_lower in ("docx", "pdf") and fmt_lower not in target_formats:
                target_formats.append(fmt_lower)  # type: ignore[arg-type]

        if not target_formats:
            target_formats = ["docx"]

        # 3. Idempotent check: if an identical verified set is already persisted, reuse it
        existing_set, reopen_err = self.engine.render_artifacts.reopen_and_verify_set(
            request_id=request_id,
            version=1,
        )
        if existing_set is not None and all(fmt in existing_set.artifacts for fmt in target_formats):
            logger.info("Reusing existing verified artifact set for request %s", request_id)
            return LocalRenderResult(status="completed", artifact_set=existing_set)

        # 4. Layout selection & pinning
        content_spec = (
            draft.template_id
            if draft.template_id in ("content-basic", "content-compact")
            else "content-basic"
        )
        layout, layout_err = self.layout_catalog.find_compatible_layout(
            document_type=draft.document_type,
            content_spec=content_spec,
            language=draft.target_language,
        )
        if layout_err or layout is None:
            return LocalRenderResult(
                status="blocked",
                error=layout_err or ClassifiedError.from_category(
                    category=ErrorCategory.MISSING_CONFIGURATION,
                    message="Compatible layout not found",
                    details={"code": "layout_unavailable"},
                ),
                reason_code="layout_unavailable",
            )

        storage_root = self.engine.artifacts_dir.parent
        pinned_layout = self.layout_catalog.pin_layout(
            request_id=request_id,
            layout=layout,
            storage_base_dir=storage_root,
        )

        # 5. Create RenderSpecification & RenderIntent
        now_utc = datetime.now(timezone.utc)
        spec = RenderSpecification(
            request_id=request_id,
            draft_id=draft.draft_id,
            draft_hash=validated_draft.draft_hash,
            report_id=validated_draft.report_id,
            report_hash=validated_draft.report_hash,
            layout_id=pinned_layout.layout_id,
            layout_version=pinned_layout.layout_version,
            layout_digest=pinned_layout.layout_digest,
            requested_formats=target_formats,
            target_language=draft.target_language,
            created_at=now_utc,
        )

        logical_key = f"{request_id}:v0001:{'+'.join(sorted(target_formats))}"
        intent = self.engine.render_artifacts.save_intent(
            RenderIntent(
                intent_id=uuid.uuid4(),
                request_id=request_id,
                logical_key=logical_key,
                spec_hash=spec.spec_hash,
                artifact_version=1,
                target_formats=target_formats,
                status="in_progress",
                created_at=now_utc,
                updated_at=now_utc,
            )
        )

        # 6. Isolated staging directory
        attempt_id = uuid.uuid4()
        staging_dir = storage_root / "staging" / "render" / str(attempt_id)
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 7. Render DOCX in staging
            docx_staging_path = staging_dir / f"{draft.document_type.value}.docx"
            start_docx_time = time.perf_counter()
            docx_start_utc = datetime.now(timezone.utc)

            docx_checks, docx_err = self.docx_renderer.render_docx(
                draft=draft,
                layout=pinned_layout,
                output_path=docx_staging_path,
            )
            docx_duration_ms = int((time.perf_counter() - start_docx_time) * 1000)

            if docx_err or docx_checks is None:
                self.engine.render_artifacts.record_attempt(
                    RenderAttempt(
                        attempt_id=uuid.uuid4(),
                        intent_id=intent.intent_id,
                        request_id=request_id,
                        attempt_number=1,
                        format="docx",
                        staging_dir=str(staging_dir),
                        started_at=docx_start_utc,
                        completed_at=datetime.now(timezone.utc),
                        status="failed",
                        exit_code=1,
                        duration_ms=docx_duration_ms,
                        error_json=docx_err.model_dump() if docx_err else None,
                    )
                )
                self.engine.render_artifacts.update_intent_status(intent.intent_id, "failed")
                return LocalRenderResult(
                    status="failed",
                    error=docx_err or ClassifiedError.validation("DOCX rendering failed"),
                    reason_code="docx_rendering_failed",
                )

            # Successful DOCX attempt
            self.engine.render_artifacts.record_attempt(
                RenderAttempt(
                    attempt_id=uuid.uuid4(),
                    intent_id=intent.intent_id,
                    request_id=request_id,
                    attempt_number=1,
                    format="docx",
                    staging_dir=str(staging_dir),
                    started_at=docx_start_utc,
                    completed_at=datetime.now(timezone.utc),
                    status="completed",
                    exit_code=0,
                    duration_ms=docx_duration_ms,
                )
            )

            docx_hash = compute_file_sha256(docx_staging_path)
            docx_size = docx_staging_path.stat().st_size
            docx_artifact_id = uuid.uuid4()
            set_id = uuid.uuid4()

            pdf_staging_path: Path | None = None
            pdf_checks: dict[str, Any] | None = None
            pdf_hash: str | None = None
            pdf_size: int | None = None
            pdf_artifact_id: uuid.UUID | None = None

            # 8. Render PDF in staging if requested
            if "pdf" in target_formats:
                start_pdf_time = time.perf_counter()
                pdf_start_utc = datetime.now(timezone.utc)

                converted_pdf, p_checks, pdf_err = self.pdf_converter.convert_docx_to_pdf(
                    saved_docx_path=docx_staging_path,
                    attempt_dir=staging_dir,
                    expected_draft=draft,
                    docx_hash=docx_hash,
                )
                pdf_duration_ms = int((time.perf_counter() - start_pdf_time) * 1000)

                if pdf_err or converted_pdf is None:
                    self.engine.render_artifacts.record_attempt(
                        RenderAttempt(
                            attempt_id=uuid.uuid4(),
                            intent_id=intent.intent_id,
                            request_id=request_id,
                            attempt_number=2,
                            format="pdf",
                            staging_dir=str(staging_dir),
                            started_at=pdf_start_utc,
                            completed_at=datetime.now(timezone.utc),
                            status="failed",
                            exit_code=1,
                            duration_ms=pdf_duration_ms,
                            error_json=pdf_err.model_dump() if pdf_err else None,
                        )
                    )
                    self.engine.render_artifacts.update_intent_status(intent.intent_id, "failed")
                    return LocalRenderResult(
                        status="failed",
                        error=pdf_err or ClassifiedError.from_category(
                            category=ErrorCategory.EXTERNAL_SERVICE_ERROR,
                            message="PDF conversion failed",
                            details={"code": "pdf_conversion_failed"},
                        ),
                        reason_code="pdf_conversion_failed",
                    )

                self.engine.render_artifacts.record_attempt(
                    RenderAttempt(
                        attempt_id=uuid.uuid4(),
                        intent_id=intent.intent_id,
                        request_id=request_id,
                        attempt_number=2,
                        format="pdf",
                        staging_dir=str(staging_dir),
                        started_at=pdf_start_utc,
                        completed_at=datetime.now(timezone.utc),
                        status="completed",
                        exit_code=0,
                        duration_ms=pdf_duration_ms,
                    )
                )

                pdf_staging_path = converted_pdf
                pdf_checks = p_checks
                pdf_hash = compute_file_sha256(pdf_staging_path)
                pdf_size = pdf_staging_path.stat().st_size
                pdf_artifact_id = uuid.uuid4()

            # 9. Atomic promotion to managed storage
            managed_dest_dir = self.engine.artifacts_dir / str(request_id) / "v0001"
            managed_dest_dir.mkdir(parents=True, exist_ok=True)

            final_docx_path = managed_dest_dir / f"{docx_artifact_id}.docx"
            shutil.move(str(docx_staging_path), str(final_docx_path))
            rel_docx_path = f"artifacts/{request_id}/v0001/{docx_artifact_id}.docx"

            receipt_docx = RenderedArtifactReceipt(
                receipt_id=uuid.uuid4(),
                request_id=request_id,
                artifact_id=docx_artifact_id,
                artifact_set_id=set_id,
                format="docx",
                version=1,
                content_hash=docx_hash,
                size_bytes=docx_size,
                local_path=str(final_docx_path),
                relative_managed_path=rel_docx_path,
                spec_hash=spec.spec_hash,
                draft_hash=validated_draft.draft_hash,
                report_hash=validated_draft.report_hash,
                layout_digest=pinned_layout.layout_digest,
                docx_artifact_id=None,
                docx_content_hash=None,
                output_checks=docx_checks or {},
                created_at=datetime.now(timezone.utc),
            )

            c14_docx = Artifact(
                artifact_id=docx_artifact_id,
                request_id=request_id,
                artifact_version=1,
                format="docx",
                local_path=str(final_docx_path),
                content_hash=docx_hash,
                size_bytes=docx_size,
                remote_file_id=None,
                delivery_status="local_only",
                approval_status=DocumentApproval.DRAFT,
                reconciliation_marker=None,
                created_at=datetime.now(timezone.utc),
            )

            slot_docx = ArtifactDeliveryRecord(
                delivery_id=uuid.uuid4(),
                request_id=request_id,
                artifact_format="docx",
                artifact_id=docx_artifact_id,
                artifact_hash=docx_hash,
                remote_file_id=None,
                delivery_status="local_only",
                delivered_at=None,
                receipt_data={},
            )

            self.engine.render_artifacts.save_receipt_and_artifact(
                receipt=receipt_docx,
                artifact=c14_docx,
                delivery_slot=slot_docx,
            )

            receipts_map: dict[str, RenderedArtifactReceipt] = {"docx": receipt_docx}

            if pdf_staging_path is not None and pdf_artifact_id is not None and pdf_hash is not None and pdf_size is not None:
                final_pdf_path = managed_dest_dir / f"{pdf_artifact_id}.pdf"
                shutil.move(str(pdf_staging_path), str(final_pdf_path))
                rel_pdf_path = f"artifacts/{request_id}/v0001/{pdf_artifact_id}.pdf"

                receipt_pdf = RenderedArtifactReceipt(
                    receipt_id=uuid.uuid4(),
                    request_id=request_id,
                    artifact_id=pdf_artifact_id,
                    artifact_set_id=set_id,
                    format="pdf",
                    version=1,
                    content_hash=pdf_hash,
                    size_bytes=pdf_size,
                    local_path=str(final_pdf_path),
                    relative_managed_path=rel_pdf_path,
                    spec_hash=spec.spec_hash,
                    draft_hash=validated_draft.draft_hash,
                    report_hash=validated_draft.report_hash,
                    layout_digest=pinned_layout.layout_digest,
                    docx_artifact_id=docx_artifact_id,
                    docx_content_hash=docx_hash,
                    output_checks=pdf_checks or {},
                    created_at=datetime.now(timezone.utc),
                )

                c14_pdf = Artifact(
                    artifact_id=pdf_artifact_id,
                    request_id=request_id,
                    artifact_version=1,
                    format="pdf",
                    local_path=str(final_pdf_path),
                    content_hash=pdf_hash,
                    size_bytes=pdf_size,
                    remote_file_id=None,
                    delivery_status="local_only",
                    approval_status=DocumentApproval.DRAFT,
                    reconciliation_marker=None,
                    created_at=datetime.now(timezone.utc),
                )

                slot_pdf = ArtifactDeliveryRecord(
                    delivery_id=uuid.uuid4(),
                    request_id=request_id,
                    artifact_format="pdf",
                    artifact_id=pdf_artifact_id,
                    artifact_hash=pdf_hash,
                    remote_file_id=None,
                    delivery_status="local_only",
                    delivered_at=None,
                    receipt_data={},
                )

                self.engine.render_artifacts.save_receipt_and_artifact(
                    receipt=receipt_pdf,
                    artifact=c14_pdf,
                    delivery_slot=slot_pdf,
                )
                receipts_map["pdf"] = receipt_pdf

            # 10. Commit ArtifactSet
            artifact_set = ArtifactSet(
                set_id=set_id,
                request_id=request_id,
                set_version=1,
                required_formats=target_formats,
                artifacts=receipts_map,
                is_complete=True,
                report_id=validated_draft.report_id,
                report_hash=validated_draft.report_hash,
                draft_hash=validated_draft.draft_hash,
                created_at=datetime.now(timezone.utc),
            )
            self.engine.render_artifacts.commit_artifact_set(artifact_set)
            self.engine.render_artifacts.update_intent_status(intent.intent_id, "completed")

            return LocalRenderResult(
                status="completed",
                artifact_set=artifact_set,
            )

        finally:
            # 11. Cleanup staging directory
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

