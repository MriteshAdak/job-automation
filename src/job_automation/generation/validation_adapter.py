"""GEN-01 DraftValidator port adapter for DraftDocumentV2 (GEN-04-S06)."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from job_automation.contracts.artifacts import DraftDocument
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.records import FreezeManifest, ValidationReport
from job_automation.generation.validation_service import DocumentValidationService

if TYPE_CHECKING:
    from job_automation.generation.validation_records import DocumentValidationReport


class DraftValidatorV2:
    """GEN-04 adapter implementing the DraftValidator protocol for GenerationCoordinator."""

    content_schema_versions = ("2.0",)

    def __init__(self, service: DocumentValidationService) -> None:
        self.service = service

    def validate_draft(
        self,
        draft: DraftDocument | DraftDocumentV2,
        manifest: FreezeManifest,
    ) -> tuple[ValidationReport | None, ClassifiedError | None]:
        """Validate C14 v2 draft against frozen inputs."""
        if not isinstance(draft, DraftDocumentV2):
            return None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="DraftValidatorV2 only supports C14 DraftDocumentV2 (schema 2.0)",
            )

        res = self.service.validate_content(draft.request_id, draft, manifest)
        if res.error or res.report is None:
            return None, res.error or ClassifiedError.validation("Document validation execution failed")

        report: DocumentValidationReport = res.report
        is_valid = (report.render_decision == "allowed_for_review")
        fatal_errors = [
            f"[{issue.code}] {issue.message}"
            for issue in report.issues
            if issue.severity == "fatal"
        ]
        warnings = [
            f"[{issue.code}] {issue.message}"
            for issue in report.issues
            if issue.severity == "warning"
        ]

        val_report = ValidationReport(
            is_valid=is_valid,
            fatal_errors=fatal_errors,
            warnings=warnings,
            validated_draft_hash=report.validated_draft_hash,
            report_ref=str(report.report_id),
        )
        return val_report, None

