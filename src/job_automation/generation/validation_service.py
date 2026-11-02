"""Document validation service orchestrating factual and structural verification (GEN-04-S05)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.draft_inputs import verify_binding
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.generation.records import FreezeManifest
from job_automation.generation.validation_consistency import validate_internal_consistency
from job_automation.generation.validation_dates import validate_dates
from job_automation.generation.validation_inputs import verify_validation_binding
from job_automation.generation.validation_metrics import validate_metrics
from job_automation.generation.validation_records import (
    DocumentValidationIssue,
    DocumentValidationReport,
    DocumentValidationSettings,
    ValidatedDraftForRendering,
    ValidationRunResult,
)
from job_automation.generation.validation_references import resolve_and_verify_references
from job_automation.generation.validation_review import assemble_validation_report
from job_automation.generation.validation_sections import validate_sections_and_structure
from job_automation.generation.validation_values import validate_values
from job_automation.storage.repositories.document_validations import DocumentValidationRepository


class DocumentValidationService:
    """Core domain service for document validation.

    Does not regenerate, edit, or approve drafts.
    Produces durable, inspectable reports separating fatal errors from review warnings.
    """

    def __init__(
        self,
        inputs: Any,
        repository: DocumentValidationRepository,
        settings: DocumentValidationSettings | None = None,
        draft_repository: Any = None,
    ) -> None:
        self.inputs = inputs
        self.repository = repository
        self.settings = settings or DocumentValidationSettings()
        self.draft_repository = draft_repository

    def validate_content(
        self,
        request_id: uuid.UUID,
        draft: DraftDocumentV2,
        manifest: FreezeManifest | None = None,
    ) -> ValidationRunResult:
        """Validate draft content and persist report atomically."""
        draft_hash = compute_sha256_digest(draft)

        # 1. Check if already committed for this request and identical content/rules
        try:
            saved_report = self.repository.get_by_request(request_id)
            if saved_report is not None:
                if (
                    saved_report.validated_draft_hash == draft_hash
                    and saved_report.input_binding.rule_set_digest == self.settings.rule_set_digest
                ):
                    return ValidationRunResult(report=saved_report)
        except Exception:
            pass  # Fall through to fresh evaluation

        # 2. Verify frozen inputs and binding
        binding, binding_issues = verify_validation_binding(
            self.inputs, request_id, draft, self.settings, self.draft_repository
        )

        if binding is None:
            # Fatal binding corruption prevents even basic evaluation
            fatal_msg = "; ".join(i.message for i in binding_issues) or "Binding verification failed"
            return ValidationRunResult(
                error=ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Validation binding failed: {fatal_msg}",
                    details={"binding_issues": [i.model_dump(mode="json") for i in binding_issues]},
                )
            )

        attempt_id = uuid.uuid4()
        started_at = datetime.now(timezone.utc)

        # Open frozen seal and context receipt
        try:
            seal, context_receipt, recipe, binding_hash = verify_binding(self.inputs, request_id)
        except Exception as exc:
            return ValidationRunResult(
                error=ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Could not verify frozen seal and receipt: {exc}",
                )
            )

        self.repository.start_attempt(
            attempt_id=attempt_id,
            request_id=request_id,
            logical_key=self.settings.rule_set_digest,
            binding_hash=binding_hash,
            draft_receipt_id=draft.provenance.receipt_id,
            draft_hash=draft_hash,
            rule_set_id=self.settings.rule_set_id,
            started_at=started_at,
        )

        # 3. Collect issues across all validation domains
        all_issues: list[DocumentValidationIssue] = list(binding_issues)

        # Reference resolution
        source_map, ref_issues = resolve_and_verify_references(draft, seal, context_receipt)
        all_issues.extend(ref_issues)

        # Dates
        date_issues = validate_dates(draft, source_map)
        all_issues.extend(date_issues)

        # Titles and identities
        value_issues = validate_values(draft, source_map, seal)
        all_issues.extend(value_issues)

        # Metrics
        metric_issues = validate_metrics(draft, source_map)
        all_issues.extend(metric_issues)

        # Section and structure
        section_issues = validate_sections_and_structure(draft, source_map)
        all_issues.extend(section_issues)

        # Consistency
        consistency_issues = validate_internal_consistency(draft, source_map)
        all_issues.extend(consistency_issues)

        # 4. Assemble report
        report = assemble_validation_report(
            request_id=request_id,
            draft=draft,
            binding=binding,
            collected_issues=all_issues,
            rule_set_id=self.settings.rule_set_id,
            validator_version=self.settings.rule_set_version,
            report_id=attempt_id,
        )

        # 5. Commit attempt and logical result to repository
        committed_report = self.repository.finish_attempt(attempt_id, report)
        return ValidationRunResult(report=committed_report)

    def reopen_report(self, report_id: uuid.UUID) -> DocumentValidationReport | None:
        """Reopen a previously committed validation report by attempt ID."""
        try:
            return self.repository.reopen(report_id)
        except Exception:
            return None

    def prepare_render_input(
        self,
        request_id: uuid.UUID,
        draft: DraftDocumentV2,
    ) -> tuple[ValidatedDraftForRendering | None, DocumentValidationReport | None]:
        """Verify validation authorization and construct ValidatedDraftForRendering envelope."""
        draft_hash = compute_sha256_digest(draft)
        report = self.repository.get_by_request(request_id)
        if report is None:
            return None, None

        if report.render_decision != "allowed_for_review":
            return None, report

        if report.validated_draft_hash != draft_hash:
            return None, report

        if report.fatal_count > 0 or report.evaluation_status != "complete":
            return None, report

        warnings_only = [i for i in report.issues if i.severity == "warning"]

        envelope = ValidatedDraftForRendering(
            draft=draft,
            draft_hash=draft_hash,
            report_id=report.report_id,
            report_hash=report.report_hash,
            binding_hash=report.input_binding.binding_hash,
            content_spec_id=report.input_binding.template_content_digest,
            render_decision="allowed_for_review",
            requires_human_review=True,
            review_warnings=warnings_only,
        )
        return envelope, report

