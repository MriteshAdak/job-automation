"""Protocols and interfaces for document validation (GEN-04-S01)."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.generation.records import FreezeManifest
from job_automation.generation.validation_records import (
    DocumentValidationReport,
    ValidatedDraftForRendering,
    ValidationRunResult,
)


@runtime_checkable
class DocumentValidationServicePort(Protocol):
    """Port for document validation service."""

    def validate_content(
        self,
        request_id: uuid.UUID,
        draft: DraftDocumentV2,
        manifest: FreezeManifest,
    ) -> ValidationRunResult:
        """Validate draft content and persist report atomically."""
        ...

    def reopen_report(
        self,
        report_id: uuid.UUID,
    ) -> DocumentValidationReport | None:
        """Reopen a previously committed validation report."""
        ...

    def prepare_render_input(
        self,
        request_id: uuid.UUID,
        draft: DraftDocumentV2,
    ) -> tuple[ValidatedDraftForRendering | None, DocumentValidationReport | None]:
        """Verify validation authorization and produce rendering input envelope."""
        ...

