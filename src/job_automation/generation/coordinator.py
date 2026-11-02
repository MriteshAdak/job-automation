"""Stage coordinator executing freeze, context, draft, validation, rendering, and delivery (GEN-01-S06)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.draft_content import DraftDocumentV2, read_draft_json
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import ContextStrategy, DocumentApproval, GenerationProcessing
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.interfaces import Generator, RendererDelivery
from job_automation.generation.errors import (
    DependencyBlockedError,
    FreezeConflictError,
    MissingComponentError,
    ProjectionUncertainError,
)
from job_automation.generation.ports import (
    ArtifactDeliverer,
    DocumentRenderer,
    DraftValidator,
    GenerationInputService,
    RequestStateProjector,
)
from job_automation.generation.records import (
    ArtifactDeliveryRecord,
    FreezeManifest,
    GenerationStage,
    ProjectionIntent,
    ProjectionStatus,
    StageAttempt,
    StageCheckpoint,
    StageStatus,
)
from job_automation.generation.request_mapping import RequestFieldMapping
from job_automation.generation.settings import GenerationSettings

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class GenerationCoordinator:
    """Coordinates the end-to-end lifecycle of a single GenerationRequest across staged checkpoints."""

    def __init__(
        self,
        engine: StorageEngine,
        projector: RequestStateProjector,
        input_service: GenerationInputService | None = None,
        generator: Generator | None = None,
        validator: DraftValidator | None = None,
        renderer: DocumentRenderer | RendererDelivery | None = None,
        deliverer: ArtifactDeliverer | RendererDelivery | None = None,
        settings: GenerationSettings | None = None,
        mapping: RequestFieldMapping | None = None,
        worker_attempt_id: uuid.UUID | None = None,
    ) -> None:
        self.engine = engine
        self.projector = projector
        self.input_service = input_service
        self.generator = generator
        self.validator = validator
        self.renderer = renderer
        self.deliverer = deliverer
        self.settings = settings or GenerationSettings()
        self.mapping = mapping or self.settings.mapping
        self.worker_attempt_id = worker_attempt_id or uuid.uuid4()

    def process_request(
        self,
        request: GenerationRequest,
        stop_after_stage: str | None = None,
    ) -> tuple[GenerationRequest, StageStatus, ClassifiedError | None]:
        """Execute or resume generation through ordered checkpoints up to stop_after_stage or completion."""
        current_req = request
        logger.info("Coordinating GenerationRequest %s (current state: %s)", current_req.request_id, current_req.state.value)

        # Stage 0: FREEZE
        current_req, freeze_status, err = self._coordinate_freeze(current_req)
        if freeze_status in (StageStatus.BLOCKED, StageStatus.FAILED):
            return current_req, freeze_status, err
        if stop_after_stage == GenerationStage.FREEZE.value:
            return current_req, freeze_status, None

        # Stage 1: CONTEXT
        manifest = self.engine.generation_work.get_freeze_association(current_req.request_id)
        if manifest is None:
            return current_req, StageStatus.FAILED, ClassifiedError.validation("Missing freeze manifest after freeze stage")

        context_bundle, context_status, err = self._coordinate_context(current_req, manifest)
        if context_status in (StageStatus.BLOCKED, StageStatus.FAILED):
            return current_req, context_status, err
        if stop_after_stage == GenerationStage.CONTEXT.value:
            return current_req, context_status, None

        # Stage 2: DRAFT
        draft_doc, draft_status, err = self._coordinate_draft(current_req, context_bundle)
        if draft_status in (StageStatus.BLOCKED, StageStatus.FAILED):
            return current_req, draft_status, err
        if stop_after_stage == GenerationStage.DRAFT.value:
            return current_req, draft_status, None

        # Stage 3: VALIDATION
        validation_status, err = self._coordinate_validation(current_req, draft_doc, manifest)
        if validation_status in (StageStatus.BLOCKED, StageStatus.FAILED):
            return current_req, validation_status, err
        if stop_after_stage == GenerationStage.VALIDATION.value:
            return current_req, validation_status, None

        # Stage 4: RENDERING
        current_req, render_status, err = self._coordinate_rendering(current_req, draft_doc)
        if render_status in (StageStatus.BLOCKED, StageStatus.FAILED):
            return current_req, render_status, err
        if stop_after_stage == GenerationStage.RENDERING.value:
            return current_req, render_status, None

        # Stage 5: DELIVERY
        current_req, deliv_status, err = self._coordinate_delivery(current_req)
        return current_req, deliv_status, err

    # -------------------------------------------------------------------------
    # Stage 0: FREEZE
    # -------------------------------------------------------------------------

    def _coordinate_freeze(
        self,
        request: GenerationRequest,
    ) -> tuple[GenerationRequest, StageStatus, ClassifiedError | None]:
        chk = self.engine.generation_work.get_checkpoint(request.request_id, GenerationStage.FREEZE.value)
        if chk and chk.status == StageStatus.COMPLETED:
            # Reconcile unacknowledged Running intent if still pending
            intent = self.engine.generation_work.get_active_projection_intent(request.request_id)
            if intent and intent.status in (ProjectionStatus.PENDING, ProjectionStatus.UNCERTAIN):
                success, proj_err = self._dispatch_or_reconcile_intent(intent)
                if not success:
                    return request, StageStatus.BLOCKED, proj_err
            return request, StageStatus.COMPLETED, None

        # Input freezing strictly requires GEN-02
        if self.input_service is None:
            err = ClassifiedError.from_category(
                category=ErrorCategory.MISSING_CONFIGURATION,
                message="GEN-02 input freezing service is absent; cannot freeze inputs inside worker",
            )
            blocked_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.FREEZE.value,
                stage_operation_id=f"freeze:{request.request_id}",
                status=StageStatus.BLOCKED,
                started_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(blocked_chk)
            return request, StageStatus.BLOCKED, err

        freeze_op_id = f"freeze:{request.request_id}:{datetime.now(timezone.utc).isoformat()}"
        manifest, freeze_err = self.input_service.prepare_freeze(request, freeze_op_id)
        now_utc = datetime.now(timezone.utc)

        if freeze_err or manifest is None:
            # Preflight failure returned by GEN-02 (e.g. job_unavailable)
            err = freeze_err or ClassifiedError.validation("GEN-02 prepare_freeze failed")
            failed_req = request.model_copy(
                update={
                    "state": GenerationProcessing.FAILED,
                    "completed_at": now_utc,
                    "error": err,
                }
            )
            self.engine.generation_requests.update_request(failed_req)

            failed_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.FREEZE.value,
                stage_operation_id=freeze_op_id,
                status=StageStatus.FAILED,
                started_at=now_utc,
                completed_at=now_utc,
                error=err,
            )
            self.engine.generation_work.save_checkpoint(failed_chk)

            # Enqueue and dispatch FAILED projection
            fail_intent = ProjectionIntent(
                request_id=request.request_id,
                projection_revision=1,
                operation_marker=f"fail:{request.request_id}:{now_utc.isoformat()}",
                desired_remote_state="Failed",
                payload={
                    self.mapping.status_field: "Failed",
                    self.mapping.error_reason_field: err.message,
                },
                status=ProjectionStatus.PENDING,
                created_at=now_utc,
                updated_at=now_utc,
            )
            self.engine.generation_work.save_projection_intent(fail_intent)
            self.projector.project_intent(fail_intent)
            return failed_req, StageStatus.FAILED, err

        # Create updated C13 request
        frozen_versions = FrozenInputVersions(
            posting_revision=manifest.posting_revision_hash,
            profile_version=manifest.profile_version,
            policy_version=manifest.policy_version,
            template_version=manifest.template_version,
        )
        claimed_req = request.model_copy(
            update={
                "state": GenerationProcessing.RUNNING,
                "claimed_at": now_utc,
                "frozen_input_versions": frozen_versions,
            }
        )

        completed_chk = StageCheckpoint(
            request_id=request.request_id,
            stage_name=GenerationStage.FREEZE.value,
            stage_operation_id=freeze_op_id,
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=now_utc,
            output_ref=manifest.manifest_id,
            output_hash=manifest.manifest_hash,
            checkpoint_data={"manifest_hash": manifest.manifest_hash},
        )

        op_marker = f"claim:{request.request_id}:{now_utc.isoformat()}"
        running_intent = ProjectionIntent(
            request_id=request.request_id,
            projection_revision=1,
            operation_marker=op_marker,
            desired_remote_state="Running",
            expected_remote_state="Pending",
            payload={
                self.mapping.status_field: "Running",
                self.mapping.worker_claimed_at_field: now_utc.isoformat(),
                self.mapping.operation_marker_field: op_marker,
            },
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )

        # Commit atomically to SQLite FIRST before network dispatch
        self.engine.generation_work.commit_frozen_request(
            request=claimed_req,
            manifest=manifest,
            checkpoint=completed_chk,
            projection_intent=running_intent,
        )

        # Dispatch Running projection intent to remote gateway
        success, proj_err = self._dispatch_or_reconcile_intent(running_intent)
        if not success:
            logger.warning("Running projection intent uncertain; halting coordinator at ordering barrier")
            return claimed_req, StageStatus.BLOCKED, proj_err

        return claimed_req, StageStatus.COMPLETED, None

    # -------------------------------------------------------------------------
    # Stage 1: CONTEXT
    # -------------------------------------------------------------------------

    def _coordinate_context(
        self,
        request: GenerationRequest,
        manifest: FreezeManifest,
    ) -> tuple[ContextBundle | None, StageStatus, ClassifiedError | None]:
        chk = self.engine.generation_work.get_checkpoint(request.request_id, GenerationStage.CONTEXT.value)
        if chk and chk.status == StageStatus.COMPLETED:
            if self.input_service is not None:
                bundle, _ = self.input_service.build_context(manifest, chk.stage_operation_id)
                if bundle:
                    return bundle, StageStatus.COMPLETED, None

        if self.input_service is None:
            err = ClassifiedError.from_category(
                category=ErrorCategory.MISSING_CONFIGURATION,
                message="GEN-02 input service is absent; cannot build context bundle",
            )
            blocked_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.CONTEXT.value,
                stage_operation_id=f"ctx:{request.request_id}",
                status=StageStatus.BLOCKED,
                started_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(blocked_chk)
            return None, StageStatus.BLOCKED, err

        now_utc = datetime.now(timezone.utc)
        ctx_op_id = f"ctx:{request.request_id}:{now_utc.isoformat()}"
        bundle, err = self.input_service.build_context(manifest, ctx_op_id)
        if err or bundle is None:
            err = err or ClassifiedError.validation("GEN-02 build_context failed")
            failed_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.CONTEXT.value,
                stage_operation_id=ctx_op_id,
                status=StageStatus.FAILED,
                started_at=now_utc,
                completed_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(failed_chk)
            return None, StageStatus.FAILED, err

        completed_chk = StageCheckpoint(
            request_id=request.request_id,
            stage_name=GenerationStage.CONTEXT.value,
            stage_operation_id=ctx_op_id,
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=datetime.now(timezone.utc),
            output_ref=str(manifest.canonical_job_id),
            checkpoint_data={"strategy": bundle.strategy.value},
        )
        self.engine.generation_work.save_checkpoint(completed_chk)
        return bundle, StageStatus.COMPLETED, None

    # -------------------------------------------------------------------------
    # Stage 2: DRAFT
    # -------------------------------------------------------------------------

    def _coordinate_draft(
        self,
        request: GenerationRequest,
        context: ContextBundle | None,
    ) -> tuple[DraftDocument | DraftDocumentV2 | None, StageStatus, ClassifiedError | None]:
        chk = self.engine.generation_work.get_checkpoint(request.request_id, GenerationStage.DRAFT.value)
        if chk and chk.status == StageStatus.COMPLETED and "draft_receipt_id" in chk.checkpoint_data:
            reopen = getattr(self.generator, "reopen_draft", None)
            if reopen is None:
                return None, StageStatus.BLOCKED, ClassifiedError.validation("C14 v2 receipt accessor required")
            try:
                draft, err = reopen(uuid.UUID(chk.checkpoint_data["draft_receipt_id"]), request, context)
            except (ValueError, TypeError):
                return None, StageStatus.FAILED, ClassifiedError.validation("Invalid C14 v2 checkpoint reference")
            if err or draft is None or draft.request_id != request.request_id or compute_sha256_digest(draft) != chk.checkpoint_data.get("draft_hash"):
                return None, StageStatus.FAILED, err or ClassifiedError.validation("C14 checkpoint integrity failure")
            return draft, StageStatus.COMPLETED, None
        if chk and chk.status == StageStatus.COMPLETED and "draft_json" in chk.checkpoint_data:
            try:
                draft = read_draft_json(chk.checkpoint_data["draft_json"])
                if isinstance(draft, DraftDocumentV2) or draft.request_id != request.request_id:
                    raise ValueError("Receipt required for C14 v2 checkpoint")
            except ValueError:
                return None, StageStatus.FAILED, ClassifiedError.validation("Unsupported or corrupt legacy draft checkpoint")
            return draft, StageStatus.COMPLETED, None
        if chk and chk.status == StageStatus.COMPLETED:
            return None, StageStatus.FAILED, ClassifiedError.validation("Completed draft checkpoint has no content reference")

        if self.generator is None:
            err = ClassifiedError.from_category(
                category=ErrorCategory.MISSING_CONFIGURATION,
                message="GEN-03 draft generator absent; cannot produce document draft",
            )
            blocked_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.DRAFT.value,
                stage_operation_id=f"draft:{request.request_id}",
                status=StageStatus.BLOCKED,
                started_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(blocked_chk)
            return None, StageStatus.BLOCKED, err

        if context is None:
            return None, StageStatus.BLOCKED, ClassifiedError.validation("Cannot draft without context bundle")

        now_utc = datetime.now(timezone.utc)
        draft_op_id = f"draft:{request.request_id}:{now_utc.isoformat()}"
        draft, err = self.generator.generate_draft(request, context)
        if err or draft is None:
            err = err or ClassifiedError.validation("GEN-03 generate_draft failed")
            failed_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.DRAFT.value,
                stage_operation_id=draft_op_id,
                status=StageStatus.FAILED,
                started_at=now_utc,
                completed_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(failed_chk)
            return None, StageStatus.FAILED, err

        completed_chk = StageCheckpoint(
            request_id=request.request_id,
            stage_name=GenerationStage.DRAFT.value,
            stage_operation_id=draft_op_id,
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=datetime.now(timezone.utc),
            output_ref=draft.document_version,
            checkpoint_data=({"draft_receipt_id": str(draft.provenance.receipt_id), "draft_hash": compute_sha256_digest(draft)}
                             if isinstance(draft, DraftDocumentV2) else {"draft_json": draft.model_dump_json()}),
        )
        self.engine.generation_work.save_checkpoint(completed_chk)
        return draft, StageStatus.COMPLETED, None

    # -------------------------------------------------------------------------
    # Stage 3: VALIDATION
    # -------------------------------------------------------------------------

    def _coordinate_validation(
        self,
        request: GenerationRequest,
        draft: DraftDocument | DraftDocumentV2 | None,
        manifest: FreezeManifest,
    ) -> tuple[StageStatus, ClassifiedError | None]:
        if self.validator is None or (isinstance(draft, DraftDocumentV2) and "2.0" not in getattr(self.validator, "content_schema_versions", ())):
            err = ClassifiedError.from_category(
                category=ErrorCategory.MISSING_CONFIGURATION,
                message="GEN-04 draft validator absent; cannot validate document",
            )
            blocked_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.VALIDATION.value,
                stage_operation_id=f"val:{request.request_id}",
                status=StageStatus.BLOCKED,
                started_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(blocked_chk)
            return StageStatus.BLOCKED, err

        if draft is None:
            return StageStatus.BLOCKED, ClassifiedError.validation("Cannot validate without draft")

        chk = self.engine.generation_work.get_checkpoint(request.request_id, GenerationStage.VALIDATION.value)
        if chk and chk.status == StageStatus.COMPLETED:
            if isinstance(draft, DraftDocumentV2):
                report = self.engine.document_validations.get_by_request(request.request_id)
                if (
                    report is None
                    or report.render_decision != "allowed_for_review"
                    or report.validated_draft_hash != compute_sha256_digest(draft)
                ):
                    return StageStatus.FAILED, ClassifiedError.validation("Validation checkpoint corrupt: durable report missing or unverified")
            return StageStatus.COMPLETED, None

        # Check if committed report exists to repair missing checkpoint after crash
        now_utc = datetime.now(timezone.utc)
        val_op_id = f"val:{request.request_id}:{now_utc.isoformat()}"

        if isinstance(draft, DraftDocumentV2):
            existing_report = self.engine.document_validations.get_by_request(request.request_id)
            if (
                existing_report is not None
                and existing_report.validated_draft_hash == compute_sha256_digest(draft)
                and existing_report.render_decision == "allowed_for_review"
            ):
                completed_chk = StageCheckpoint(
                    request_id=request.request_id,
                    stage_name=GenerationStage.VALIDATION.value,
                    stage_operation_id=val_op_id,
                    status=StageStatus.COMPLETED,
                    started_at=now_utc,
                    completed_at=now_utc,
                    output_ref=existing_report.validated_draft_hash,
                    checkpoint_data={
                        "warnings": [i.message for i in existing_report.issues if i.severity == "warning"],
                        "report_ref": str(existing_report.report_id),
                        "validated_draft_hash": existing_report.validated_draft_hash,
                    },
                )
                self.engine.generation_work.save_checkpoint(completed_chk)
                return StageStatus.COMPLETED, None

        report, err = self.validator.validate_draft(draft, manifest)
        if err or report is None:
            err = err or ClassifiedError.validation("GEN-04 validation failed")
            failed_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.VALIDATION.value,
                stage_operation_id=val_op_id,
                status=StageStatus.FAILED,
                started_at=now_utc,
                completed_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(failed_chk)
            return StageStatus.FAILED, err

        if not report.is_valid or report.fatal_errors:
            fatal_msg = "; ".join(report.fatal_errors) or "Fatal validation errors detected"
            val_err = ClassifiedError.validation(fatal_msg)
            failed_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.VALIDATION.value,
                stage_operation_id=val_op_id,
                status=StageStatus.FAILED,
                started_at=now_utc,
                completed_at=datetime.now(timezone.utc),
                error=val_err,
                checkpoint_data={"report": report.model_dump()},
            )
            self.engine.generation_work.save_checkpoint(failed_chk)

            # Update request to Failed
            failed_req = request.model_copy(
                update={
                    "state": GenerationProcessing.FAILED,
                    "completed_at": datetime.now(timezone.utc),
                    "error": val_err,
                }
            )
            self.engine.generation_requests.update_request(failed_req)

            # Enqueue & dispatch Failed projection
            intent = ProjectionIntent(
                request_id=request.request_id,
                projection_revision=2,
                operation_marker=f"val_fail:{request.request_id}:{now_utc.isoformat()}",
                desired_remote_state="Failed",
                payload={
                    self.mapping.status_field: "Failed",
                    self.mapping.error_reason_field: fatal_msg,
                },
                status=ProjectionStatus.PENDING,
                created_at=now_utc,
                updated_at=now_utc,
            )
            self.engine.generation_work.save_projection_intent(intent)
            self.projector.project_intent(intent)
            return StageStatus.FAILED, val_err

        completed_chk = StageCheckpoint(
            request_id=request.request_id,
            stage_name=GenerationStage.VALIDATION.value,
            stage_operation_id=val_op_id,
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=datetime.now(timezone.utc),
            output_ref=report.validated_draft_hash,
            checkpoint_data={
                "warnings": report.warnings,
                "report_ref": report.report_ref,
                "validated_draft_hash": report.validated_draft_hash,
            },
        )
        self.engine.generation_work.save_checkpoint(completed_chk)
        return StageStatus.COMPLETED, None

    # -------------------------------------------------------------------------
    # Stage 4: RENDERING
    # -------------------------------------------------------------------------

    def _coordinate_rendering(
        self,
        request: GenerationRequest,
        draft: DraftDocument | DraftDocumentV2 | None,
    ) -> tuple[GenerationRequest, StageStatus, ClassifiedError | None]:
        chk = self.engine.generation_work.get_checkpoint(request.request_id, GenerationStage.RENDERING.value)
        if chk and chk.status == StageStatus.COMPLETED:
            return request, StageStatus.COMPLETED, None

        if self.renderer is None:
            err = ClassifiedError.from_category(
                category=ErrorCategory.MISSING_CONFIGURATION,
                message="GEN-05 renderer absent; cannot render document",
            )
            blocked_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.RENDERING.value,
                stage_operation_id=f"render:{request.request_id}",
                status=StageStatus.BLOCKED,
                started_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(blocked_chk)
            return request, StageStatus.BLOCKED, err

        if draft is None:
            return request, StageStatus.BLOCKED, ClassifiedError.validation("Cannot render without draft")

        if isinstance(draft, DraftDocumentV2):
            val_chk = self.engine.generation_work.get_checkpoint(request.request_id, GenerationStage.VALIDATION.value)
            if val_chk is None or val_chk.status != StageStatus.COMPLETED:
                err = ClassifiedError.validation("Rendering blocked: draft validation stage not completed")
                blocked_chk = StageCheckpoint(
                    request_id=request.request_id,
                    stage_name=GenerationStage.RENDERING.value,
                    stage_operation_id=f"render:{request.request_id}",
                    status=StageStatus.BLOCKED,
                    started_at=datetime.now(timezone.utc),
                    error=err,
                )
                self.engine.generation_work.save_checkpoint(blocked_chk)
                return request, StageStatus.BLOCKED, err

            report = self.engine.document_validations.get_by_request(request.request_id)
            if (
                report is None
                or report.render_decision != "allowed_for_review"
                or report.validated_draft_hash != compute_sha256_digest(draft)
                or report.fatal_count > 0
            ):
                err = ClassifiedError.validation("Rendering blocked: draft validation authorization missing or invalid")
                blocked_chk = StageCheckpoint(
                    request_id=request.request_id,
                    stage_name=GenerationStage.RENDERING.value,
                    stage_operation_id=f"render:{request.request_id}",
                    status=StageStatus.BLOCKED,
                    started_at=datetime.now(timezone.utc),
                    error=err,
                )
                self.engine.generation_work.save_checkpoint(blocked_chk)
                return request, StageStatus.BLOCKED, err

        now_utc = datetime.now(timezone.utc)
        render_op_id = f"render:{request.request_id}:{now_utc.isoformat()}"
        required_formats = self.settings.required_formats

        for fmt in required_formats:
            existing_deliv = self.engine.generation_work.get_delivery_record(request.request_id, fmt)
            if existing_deliv is not None:
                # Format already rendered in earlier attempt
                continue

            dest_path = str(self.engine.artifacts_dir / f"{request.request_id}.{fmt}")
            if hasattr(self.renderer, "render_document"):
                art, err = self.renderer.render_document(draft, fmt, dest_path, render_op_id)
            else:
                art, err = self.renderer.render(draft, fmt, dest_path)

            if err or art is None:
                err = err or ClassifiedError.validation(f"Failed to render format '{fmt}'")
                failed_chk = StageCheckpoint(
                    request_id=request.request_id,
                    stage_name=GenerationStage.RENDERING.value,
                    stage_operation_id=render_op_id,
                    status=StageStatus.FAILED,
                    started_at=now_utc,
                    completed_at=datetime.now(timezone.utc),
                    error=err,
                )
                self.engine.generation_work.save_checkpoint(failed_chk)
                return request, StageStatus.FAILED, err

            # Save delivery slot record
            deliv_rec = ArtifactDeliveryRecord(
                request_id=request.request_id,
                artifact_format=fmt,
                artifact_id=art.artifact_id,
                artifact_hash=art.content_hash,
                delivery_status="local_only",
            )
            self.engine.generation_work.save_delivery_record(deliv_rec)
            if self.engine.artifacts.get_artifact(art.artifact_id) is None:
                self.engine.artifacts.save_artifact(art)

        # Transition request to UPLOAD_PENDING
        upload_pending_req = request.model_copy(
            update={
                "state": GenerationProcessing.UPLOAD_PENDING,
                "result_artifact_ref": str(self.engine.artifacts_dir / f"{request.request_id}.docx"),
            }
        )
        self.engine.generation_requests.update_request(upload_pending_req)

        completed_chk = StageCheckpoint(
            request_id=request.request_id,
            stage_name=GenerationStage.RENDERING.value,
            stage_operation_id=render_op_id,
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=datetime.now(timezone.utc),
            output_ref=upload_pending_req.result_artifact_ref,
            checkpoint_data={"rendered_formats": required_formats},
        )
        self.engine.generation_work.save_checkpoint(completed_chk)
        return upload_pending_req, StageStatus.COMPLETED, None

    # -------------------------------------------------------------------------
    # Stage 5: DELIVERY
    # -------------------------------------------------------------------------

    def _coordinate_delivery(
        self,
        request: GenerationRequest,
    ) -> tuple[GenerationRequest, StageStatus, ClassifiedError | None]:
        chk = self.engine.generation_work.get_checkpoint(request.request_id, GenerationStage.DELIVERY.value)
        if chk and chk.status == StageStatus.COMPLETED:
            return request, StageStatus.COMPLETED, None

        if self.deliverer is None:
            err = ClassifiedError.from_category(
                category=ErrorCategory.MISSING_CONFIGURATION,
                message="GEN-06 deliverer absent; cannot deliver artifacts to Salesforce Files",
            )
            blocked_chk = StageCheckpoint(
                request_id=request.request_id,
                stage_name=GenerationStage.DELIVERY.value,
                stage_operation_id=f"deliv:{request.request_id}",
                status=StageStatus.BLOCKED,
                started_at=datetime.now(timezone.utc),
                error=err,
            )
            self.engine.generation_work.save_checkpoint(blocked_chk)
            return request, StageStatus.BLOCKED, err

        now_utc = datetime.now(timezone.utc)
        deliv_op_id = f"deliv:{request.request_id}:{now_utc.isoformat()}"
        required_formats = self.settings.required_formats
        set_receipt = None

        if hasattr(self.deliverer, "deliver_or_reconcile"):
            art_set = self.engine.render_artifacts.get_artifact_set(request.request_id)
            if art_set is None:
                receipts = self.engine.render_artifacts.get_receipts_by_request(request.request_id)
                if receipts:
                    from job_automation.generation.render_records import ArtifactSet
                    receipts_map = {r.format: r for r in receipts}
                    art_set = ArtifactSet(
                        request_id=request.request_id,
                        set_version=receipts[0].version,
                        required_formats=required_formats,
                        artifacts=receipts_map,
                        report_id=receipts[0].artifact_set_id,
                        report_hash=receipts[0].report_hash,
                        draft_hash=receipts[0].draft_hash,
                        created_at=now_utc,
                    )
            if art_set is not None:
                sf_req_id = request.salesforce_request_id or ""
                can_sf_id: str | None = None
                obs_rows = self.engine.conn.execute(
                    "SELECT salesforce_request_id, canonical_salesforce_id FROM generation_request_observations WHERE local_request_id = ?",
                    (str(request.request_id),),
                ).fetchall()
                if obs_rows:
                    sf_req_id = obs_rows[0]["salesforce_request_id"] or sf_req_id
                    can_sf_id = obs_rows[0]["canonical_salesforce_id"] or None
                if not sf_req_id:
                    sf_req_id = f"a01{uuid.uuid4().hex[:12]}"

                set_receipt, err = self.deliverer.deliver_or_reconcile(
                    request=request,
                    artifact_set=art_set,
                    salesforce_request_id=sf_req_id,
                    canonical_salesforce_id=can_sf_id,
                )
                if err or set_receipt is None:
                    err = err or ClassifiedError.transient_network("Delivery failed")
                    return request, StageStatus.BLOCKED, err

        if set_receipt is None:
            for fmt in required_formats:
                deliv_rec = self.engine.generation_work.get_delivery_record(request.request_id, fmt)
                if deliv_rec is None:
                    return request, StageStatus.FAILED, ClassifiedError.validation(f"Missing artifact slot for format '{fmt}'")

                if deliv_rec.delivery_status == "delivered" and deliv_rec.remote_file_id:
                    # Format already delivered
                    continue

                art = self.engine.artifacts.get_artifact(deliv_rec.artifact_id)
                if art is None:
                    return request, StageStatus.FAILED, ClassifiedError.validation(f"Artifact {deliv_rec.artifact_id} not found")

                # Dispatch delivery
                if hasattr(self.deliverer, "deliver_artifact"):
                    receipt, err = self.deliverer.deliver_artifact(art, self.projector.gateway, deliv_op_id)
                    if err or receipt is None:
                        err = err or ClassifiedError.transient_network(f"Delivery failed for {fmt}")
                        return request, StageStatus.BLOCKED, err
                    deliv_rec.delivery_status = receipt.delivery_status
                    deliv_rec.remote_file_id = receipt.remote_file_id
                    deliv_rec.delivered_at = receipt.delivered_at or datetime.now(timezone.utc)
                    deliv_rec.receipt_data = receipt.receipt_data
                else:
                    delivered_art, err = self.deliverer.deliver(art, self.projector.gateway)
                    if err or delivered_art is None:
                        err = err or ClassifiedError.transient_network(f"Delivery failed for {fmt}")
                        return request, StageStatus.BLOCKED, err
                    deliv_rec.delivery_status = delivered_art.delivery_status
                    deliv_rec.remote_file_id = delivered_art.remote_file_id
                    deliv_rec.delivered_at = datetime.now(timezone.utc)

                self.engine.generation_work.save_delivery_record(deliv_rec)

        # All required formats are successfully delivered!
        ready_req = request.model_copy(
            update={
                "state": GenerationProcessing.READY_FOR_REVIEW,
                "completed_at": datetime.now(timezone.utc),
            }
        )
        self.engine.generation_requests.update_request(ready_req)

        completed_chk = StageCheckpoint(
            request_id=request.request_id,
            stage_name=GenerationStage.DELIVERY.value,
            stage_operation_id=deliv_op_id,
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=datetime.now(timezone.utc),
            output_ref=ready_req.result_artifact_ref,
        )
        self.engine.generation_work.save_checkpoint(completed_chk)

        # Enqueue & dispatch Ready_for_Review projection
        last_intent = self.engine.generation_work.get_active_projection_intent(request.request_id)
        next_revision = (last_intent.projection_revision + 1) if last_intent else 3
        set_ver = set_receipt.set_version if set_receipt else 1
        op_marker = f"ready:{request.request_id}:{set_ver}:{now_utc.strftime('%Y%m%d%H%M%S')}"

        ready_payload = {
            self.mapping.status_field: "Ready_for_Review",
            self.mapping.operation_marker_field: op_marker,
        }
        primary_deliv = (
            self.engine.generation_work.get_delivery_record(request.request_id, "docx")
            or self.engine.generation_work.get_delivery_record(request.request_id, "pdf")
        )
        if primary_deliv and primary_deliv.remote_file_id:
            ready_payload[self.mapping.result_artifact_field] = primary_deliv.remote_file_id

        ready_intent = ProjectionIntent(
            request_id=request.request_id,
            projection_revision=next_revision,
            operation_marker=op_marker,
            desired_remote_state="Ready_for_Review",
            payload=ready_payload,
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        self.engine.generation_work.save_projection_intent(ready_intent)
        self.projector.project_intent(ready_intent)

        return ready_req, StageStatus.COMPLETED, None

    # -------------------------------------------------------------------------
    # Helper: Dispatch or Reconcile Projection Intent
    # -------------------------------------------------------------------------

    def _dispatch_or_reconcile_intent(
        self, intent: ProjectionIntent
    ) -> tuple[bool, ClassifiedError | None]:
        if intent.status == ProjectionStatus.UNCERTAIN:
            return self.projector.reconcile_intent(intent)
        return self.projector.project_intent(intent)
