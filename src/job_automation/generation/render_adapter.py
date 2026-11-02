"""Adapter bridging GenerationCoordinator with GEN-05 RenderService (GEN-05-S06)."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.enums import DocumentApproval
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.generation.ports import DocumentRenderer
from job_automation.generation.render_service import RenderService
from job_automation.generation.validation_records import ValidatedDraftForRendering

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class DocumentRendererAdapter(DocumentRenderer):
    """Adapter implementing DocumentRenderer protocol for GenerationCoordinator stage execution."""

    def __init__(
        self,
        render_service: RenderService,
        engine: StorageEngine,
    ) -> None:
        self.render_service = render_service
        self.engine = engine

    def render_document(
        self,
        draft: DraftDocument | DraftDocumentV2,
        output_format: str,
        destination_path: str,
        op_id: str,
    ) -> tuple[Artifact | None, ClassifiedError | None]:
        """Render a draft into the requested format (DOCX or PDF) via RenderService."""
        fmt = output_format.lower()
        if fmt not in ("docx", "pdf"):
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Unsupported rendering output format: '{output_format}'",
                details={"code": "unsupported_format"},
            )

        if not isinstance(draft, DraftDocumentV2):
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Renderer requires DraftDocumentV2; received {type(draft).__name__}",
                details={"code": "unsupported_draft_type"},
            )

        # Retrieve validation report from durable store
        report = self.engine.document_validations.get_by_request(draft.request_id)
        if report is None:
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Rendering blocked: no validation report found for request {draft.request_id}",
                details={"code": "validation_report_missing"},
            )

        draft_digest = compute_sha256_digest(draft)
        if report.validated_draft_hash != draft_digest:
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="Rendering blocked: validated draft hash does not match current draft",
                details={"code": "draft_hash_mismatch"},
            )

        if report.render_decision != "allowed_for_review" or report.fatal_count > 0:
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Rendering blocked: validation decision '{report.render_decision}' with {report.fatal_count} fatal issues",
                details={"code": "render_authorization_denied"},
            )

        # Construct ValidatedDraftForRendering envelope
        val_draft = ValidatedDraftForRendering(
            draft=draft,
            draft_hash=draft_digest,
            report_id=report.report_id,
            report_hash=report.report_hash,
            binding_hash=report.input_binding.binding_hash,
            content_spec_id="2.0",
            render_decision="allowed_for_review",
            requires_human_review=True,
            review_warnings=report.issues,
        )

        result = self.render_service.render_or_reopen(
            validated_draft=val_draft,
            requested_formats=[fmt],
        )

        if result.status != "completed" or result.artifact_set is None:
            return None, result.error or ClassifiedError.validation(f"Failed to render format '{fmt}'")

        receipt = result.artifact_set.artifacts.get(fmt)
        if receipt is None:
            return None, ClassifiedError.validation(f"Rendered artifact set missing receipt for format '{fmt}'")

        art = self.engine.artifacts.get_artifact(receipt.artifact_id)
        if art is None:
            return None, ClassifiedError.validation(f"Persisted artifact not found for artifact ID {receipt.artifact_id}")

        # If coordinator requested a distinct destination path, copy file there
        dest = Path(destination_path)
        if dest.resolve() != Path(receipt.local_path).resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(receipt.local_path, dest)
            art = art.model_copy(update={"local_path": str(dest)})

        return art, None
