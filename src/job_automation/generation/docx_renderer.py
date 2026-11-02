"""DOCX generation and output verification runner (GEN-05-S03)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.render_checks import verify_docx_file
from job_automation.generation.render_projection import project_draft_to_docx
from job_automation.generation.render_records import ApprovedLayout

logger = logging.getLogger(__name__)


class DocxRenderer:
    """Renderer constructing editable DOCX files and validating their structural output."""

    def render_docx(
        self,
        draft: DraftDocumentV2,
        layout: ApprovedLayout,
        output_path: Path,
    ) -> tuple[dict[str, Any] | None, ClassifiedError | None]:
        """Project validated draft to DOCX, verify file structure and exact content coverage."""
        try:
            projection_summary = project_draft_to_docx(draft, layout, output_path)
        except Exception as exc:
            logger.error("Failed to build DOCX at %s: %s", output_path, exc)
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Failed to project draft to DOCX: {exc}",
                details={"code": "docx_projection_failed"},
            )

        # Verify output file
        valid, checks, failure_reason = verify_docx_file(output_path, draft)
        if not valid or failure_reason:
            logger.error("DOCX output verification failed for %s: %s", output_path, failure_reason)
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"DOCX output verification failed: {failure_reason}",
                details={"code": "render_output_invalid", "checks": checks},
            )

        checks.update(projection_summary)
        return checks, None

