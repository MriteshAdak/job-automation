"""Standalone, worker-independent GenerationInputService implementation for GEN-02."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import ContextStrategy, GenerationProcessing
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.interfaces import ModelProvider
from job_automation.context.chunk_identity import compute_snapshot_fingerprint
from job_automation.generation.input_availability import AvailabilityRechecker
from job_automation.generation.input_context import ContextAssembler
from job_automation.generation.input_errors import (
    freeze_conflict_error,
    frozen_input_corrupt_error,
    frozen_input_missing_error,
)
from job_automation.generation.input_indexes import resolve_and_pin_rag_index
from job_automation.generation.input_ports import StandaloneGenerationInputService
from job_automation.generation.input_records import (
    FreezeManifest,
    FrozenContextReceipt,
    FrozenGenerationOptions,
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
    FrozenSeal,
    GenerationInputSettings,
    PreflightReceipt,
    compute_manifest_hash,
    compute_sha256_digest,
)
from job_automation.generation.input_resolution import InputResolver
from job_automation.generation.ports import GenerationInputService
from job_automation.generation.request_mapping import compute_options_digest
from job_automation.storage.connection import transaction

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class DefaultGenerationInputService(GenerationInputService, StandaloneGenerationInputService):
    """Complete, worker-independent GEN-02 service for input freezing and context assembly.

    Guarantees:
    - Independent of GEN-01 worker: runs without leases, loops, or remote mutations.
    - Rechecks authoritative availability against IDENTITY-02 at sealing.
    - Freezes exact C01 approved profile, C06 normalized posting, options, and recipe.
    - Emits durable, inspectable PreflightReceipt on success and on failure.
    - Enforces freeze-once invariance: raises FreezeConflictError on modified options.
    - Assembles both JSON and RAG contexts strictly from sealed inputs.
    - Replay of context assembly is byte-for-byte identical with zero model calls.
    """

    def __init__(
        self,
        engine: StorageEngine,
        settings: GenerationInputSettings | None = None,
        model_provider: ModelProvider | None = None,
        recipe_provider: Any = None,
    ) -> None:
        self.engine = engine
        self.settings = settings or GenerationInputSettings()
        self.model_provider = model_provider
        self.availability_rechecker = AvailabilityRechecker(engine=self.engine)
        self.input_resolver = InputResolver(engine=self.engine, settings=self.settings, recipe_provider=recipe_provider)
        self.context_assembler = ContextAssembler(engine=self.engine, model_provider=self.model_provider)

    def prepare_freeze(
        self,
        request: GenerationRequest,
        freeze_op_id: str,
    ) -> tuple[FreezeManifest | None, ClassifiedError | None]:
        """Validate options, recheck availability, and atomically seal inputs into durable storage.

        Returns:
            tuple[FreezeManifest | None, ClassifiedError | None] where exactly one element is non-null.
        """
        started_at = datetime.now(timezone.utc)
        strict_override = request.allow_unavailable_job is True

        opts_dict: dict[str, Any] = {
            "canonical_job_id": str(request.canonical_job_id),
            "document_type": request.document_type.value,
            "target_language": request.target_language,
            "template_id": request.template_id,
            "context_strategy": request.context_strategy.value,
            "allow_unavailable_job": strict_override,
        }
        current_options_digest = compute_options_digest(opts_dict)

        # ---------------------------------------------------------------------
        # T0 Check: Existing Seal and Conflict Detection
        # ---------------------------------------------------------------------
        existing_seal = self.engine.generation_inputs.get_seal_by_request_id(request.request_id)
        if existing_seal is not None:
            if existing_seal.options.options_digest != current_options_digest:
                err = freeze_conflict_error(
                    request_id=request.request_id,
                    message=(
                        f"Request {request.request_id} is already sealed with different options "
                        f"(existing: {existing_seal.options.options_digest}, current: {current_options_digest})"
                    ),
                )
                return None, err
            # Idempotent replay: return copy of existing manifest
            return existing_seal.manifest.model_copy(deep=True), None

        # ---------------------------------------------------------------------
        # Availability Recheck
        # ---------------------------------------------------------------------
        avail_check, avail_err = self.availability_rechecker.recheck_availability(
            canonical_job_id=request.canonical_job_id,
            allow_unavailable_job=strict_override,
            override_provenance=f"candidate_request:{request.request_id}",
        )

        if avail_err is not None or avail_check is None:
            now_utc = datetime.now(timezone.utc)
            fail_receipt = PreflightReceipt(
                request_id=request.request_id,
                accepted_options_digest=current_options_digest,
                freeze_op_id=freeze_op_id,
                started_at=started_at,
                completed_at=now_utc,
                result="failed",
                seal_id=None,
                seal_hash=None,
                warnings=avail_check.warnings if avail_check else [],
                error=avail_err,
                reason_code=avail_err.details.get("reason_code") if avail_err else "job_unavailable",
            )
            # Atomically save preflight failure receipt and update C13 if request exists
            with transaction(self.engine.conn):
                self.engine.generation_inputs.save_preflight_receipt(fail_receipt)
                existing_c13 = self.engine.generation_requests.get_request(request.request_id)
                if existing_c13 is not None and existing_c13.state == GenerationProcessing.PENDING:
                    failed_c13 = existing_c13.model_copy(
                        update={
                            "state": GenerationProcessing.FAILED,
                            "completed_at": now_utc,
                            "error": avail_err,
                        }
                    )
                    self.engine.generation_requests.update_request(failed_c13)

            return None, avail_err

        # ---------------------------------------------------------------------
        # Preparation Outside Write Lock: Resolve Job, Profile, Recipe
        # ---------------------------------------------------------------------
        resolved, res_err = self.input_resolver.resolve_inputs(request, freeze_op_id)
        if res_err is not None or resolved is None:
            now_utc = datetime.now(timezone.utc)
            fail_receipt = PreflightReceipt(
                request_id=request.request_id,
                accepted_options_digest=current_options_digest,
                freeze_op_id=freeze_op_id,
                started_at=started_at,
                completed_at=now_utc,
                result="failed",
                seal_id=None,
                seal_hash=None,
                warnings=avail_check.warnings,
                error=res_err,
                reason_code=res_err.details.get("reason_code") if res_err else "input_resolution_failed",
            )
            with transaction(self.engine.conn):
                self.engine.generation_inputs.save_preflight_receipt(fail_receipt)
                existing_c13 = self.engine.generation_requests.get_request(request.request_id)
                if existing_c13 is not None and existing_c13.state == GenerationProcessing.PENDING:
                    failed_c13 = existing_c13.model_copy(
                        update={
                            "state": GenerationProcessing.FAILED,
                            "completed_at": now_utc,
                            "error": res_err,
                        }
                    )
                    self.engine.generation_requests.update_request(failed_c13)

            return None, res_err

        job_snap, profile_snap, options, recipe = resolved

        # ---------------------------------------------------------------------
        # AUTO-02 Preflight Guard: Verify Automatic Bindings Before Claim
        # ---------------------------------------------------------------------
        auto_binding = self.engine.automatic_drafts.get_binding_by_request_id(request.request_id)
        if auto_binding is not None:
            from job_automation.generation.automatic.preflight import AutomaticPreflightGuard
            guard = AutomaticPreflightGuard(self.engine)
            ok, auto_err, receipt = guard.verify_request_preflight(
                request=request,
                resolved_job=job_snap,
                resolved_profile=profile_snap,
            )
            if not ok or auto_err is not None:
                now_utc = datetime.now(timezone.utc)
                fail_receipt = PreflightReceipt(
                    request_id=request.request_id,
                    accepted_options_digest=current_options_digest,
                    freeze_op_id=freeze_op_id,
                    started_at=started_at,
                    completed_at=now_utc,
                    result="failed",
                    seal_id=None,
                    seal_hash=None,
                    warnings=avail_check.warnings if avail_check else [],
                    error=auto_err,
                    reason_code=auto_err.details.get("reason_code") if auto_err else "auto_preflight_failed",
                )
                with transaction(self.engine.conn):
                    self.engine.generation_inputs.save_preflight_receipt(fail_receipt)
                    existing_c13 = self.engine.generation_requests.get_request(request.request_id)
                    if existing_c13 is not None and existing_c13.state == GenerationProcessing.PENDING:
                        failed_c13 = existing_c13.model_copy(
                            update={
                                "state": GenerationProcessing.FAILED,
                                "completed_at": now_utc,
                                "error": auto_err,
                            }
                        )
                        self.engine.generation_requests.update_request(failed_c13)
                return None, auto_err

        # ---------------------------------------------------------------------
        # RAG Index Resolution and Pinning (if RAG strategy)
        # ---------------------------------------------------------------------
        pinned_gen_id: uuid.UUID | None = None
        index_pin_id: uuid.UUID | None = None

        if options.context_strategy == ContextStrategy.RAG:
            p_gen_id, p_pin_id, rag_err = resolve_and_pin_rag_index(
                indexes_dir=self.engine.indexes_dir,
                repository=self.engine.context_indexes,
                request_id=request.request_id,
                candidate_id=profile_snap.candidate_id,
                purpose=options.purpose,
                profile_version=profile_snap.profile_version,
                snapshot_fingerprint=compute_snapshot_fingerprint(profile_snap.snapshot),
            )
            if rag_err is not None or p_gen_id is None or p_pin_id is None:
                now_utc = datetime.now(timezone.utc)
                fail_receipt = PreflightReceipt(
                    request_id=request.request_id,
                    accepted_options_digest=current_options_digest,
                    freeze_op_id=freeze_op_id,
                    started_at=started_at,
                    completed_at=now_utc,
                    result="failed",
                    seal_id=None,
                    seal_hash=None,
                    warnings=avail_check.warnings,
                    error=rag_err,
                    reason_code=rag_err.details.get("reason_code") if rag_err else "frozen_index_mismatch",
                )
                with transaction(self.engine.conn):
                    self.engine.generation_inputs.save_preflight_receipt(fail_receipt)
                    existing_c13 = self.engine.generation_requests.get_request(request.request_id)
                    if existing_c13 is not None and existing_c13.state == GenerationProcessing.PENDING:
                        failed_c13 = existing_c13.model_copy(
                            update={
                                "state": GenerationProcessing.FAILED,
                                "completed_at": now_utc,
                                "error": rag_err,
                            }
                        )
                        self.engine.generation_requests.update_request(failed_c13)

                return None, rag_err

            pinned_gen_id = p_gen_id
            index_pin_id = p_pin_id

        # ---------------------------------------------------------------------
        # Build Manifest and Seal
        # ---------------------------------------------------------------------
        now_utc = datetime.now(timezone.utc)
        manifest_id = f"manifest:{request.request_id}"

        snapshot_refs: dict[str, str] = {
            "job_snapshot": job_snap.snapshot_digest,
            "profile_snapshot": profile_snap.snapshot_digest,
            "recipe": recipe.recipe_digest,
            "options": options.options_digest,
            "availability_check": avail_check.check_digest,
        }
        if pinned_gen_id is not None:
            snapshot_refs["pinned_index_generation_id"] = str(pinned_gen_id)
        if index_pin_id is not None:
            snapshot_refs["index_pin_id"] = str(index_pin_id)

        manifest_data: dict[str, Any] = {
            "manifest_id": manifest_id,
            "canonical_job_id": str(request.canonical_job_id),
            "posting_revision_id": job_snap.posting_revision_id,
            "posting_revision_hash": job_snap.posting_revision_hash,
            "profile_version": profile_snap.profile_version,
            "policy_version": self.settings.default_template_version,
            "template_id": options.template_id,
            "template_version": options.template_version,
            "context_strategy": options.context_strategy.value,
            "target_language": options.target_language,
            "options_digest": options.options_digest,
            "availability_status": avail_check.canonical_availability.value,
            "allow_unavailable_job": strict_override,
            "frozen_at": now_utc.isoformat(),
            "snapshot_refs": snapshot_refs,
            "warnings": sorted(avail_check.warnings),
        }
        manifest_hash = compute_manifest_hash(manifest_data)

        manifest = FreezeManifest(
            manifest_id=manifest_id,
            manifest_hash=manifest_hash,
            canonical_job_id=request.canonical_job_id,
            posting_revision_id=job_snap.posting_revision_id,
            posting_revision_hash=job_snap.posting_revision_hash,
            profile_version=profile_snap.profile_version,
            policy_version=self.settings.default_template_version,
            template_id=options.template_id,
            template_version=options.template_version,
            context_strategy=options.context_strategy,
            target_language=options.target_language,
            options_digest=options.options_digest,
            availability_status=avail_check.canonical_availability.value,
            allow_unavailable_job=strict_override,
            frozen_at=now_utc,
            snapshot_refs=snapshot_refs,
            warnings=sorted(avail_check.warnings),
        )

        seal_id = f"seal:{request.request_id}"
        seal_hash_payload = {
            "seal_id": seal_id,
            "request_id": str(request.request_id),
            "manifest_hash": manifest_hash,
            "job_snapshot_digest": job_snap.snapshot_digest,
            "profile_snapshot_digest": profile_snap.snapshot_digest,
            "recipe_digest": recipe.recipe_digest,
            "options_digest": options.options_digest,
        }
        seal_hash = compute_sha256_digest(seal_hash_payload)

        body_hash = None
        if recipe.content_recipe_json is not None:
            body_hash = compute_sha256_digest({
                "job": job_snap, "profile": profile_snap, "options": options,
                "recipe": recipe, "availability": avail_check,
            })
            seal_hash_payload["body_hash"] = body_hash
            seal_hash = compute_sha256_digest(seal_hash_payload)

        seal = FrozenSeal(
            seal_id=seal_id,
            request_id=request.request_id,
            candidate_id=profile_snap.candidate_id,
            canonical_job_id=request.canonical_job_id,
            manifest=manifest,
            options=options,
            job_snapshot=job_snap,
            profile_snapshot=profile_snap,
            availability_check=avail_check,
            recipe=recipe,
            pinned_index_generation_id=pinned_gen_id,
            index_pin_id=index_pin_id,
            sealed_at=now_utc,
            seal_hash=seal_hash,
            body_hash=body_hash,
        )

        receipt = PreflightReceipt(
            request_id=request.request_id,
            accepted_options_digest=options.options_digest,
            freeze_op_id=freeze_op_id,
            started_at=started_at,
            completed_at=now_utc,
            result="prepared",
            seal_id=seal_id,
            seal_hash=seal_hash,
            warnings=sorted(avail_check.warnings),
            error=None,
            reason_code=None,
        )

        # ---------------------------------------------------------------------
        # T1 Commit: Atomically persist seal, snapshots, and preflight receipt
        # ---------------------------------------------------------------------
        with transaction(self.engine.conn):
            self.engine.generation_inputs.save_seal(seal)
            self.engine.generation_inputs.save_preflight_receipt(receipt)

        return manifest.model_copy(deep=True), None

    def reopen_freeze(
        self,
        manifest_id: str,
    ) -> tuple[FreezeManifest | None, ClassifiedError | None]:
        """Reopen and integrity-verify an existing sealed freeze manifest."""
        seal = self.engine.generation_inputs.get_seal_by_manifest_id(manifest_id)
        if seal is None:
            return None, frozen_input_missing_error(manifest_id)

        # Verify seal integrity
        expected_seal_hash_payload = {
            "seal_id": seal.seal_id,
            "request_id": str(seal.request_id),
            "manifest_hash": seal.manifest.manifest_hash,
            "job_snapshot_digest": seal.job_snapshot.snapshot_digest,
            "profile_snapshot_digest": seal.profile_snapshot.snapshot_digest,
            "recipe_digest": seal.recipe.recipe_digest,
            "options_digest": seal.options.options_digest,
        }
        recomputed_hash = compute_sha256_digest(expected_seal_hash_payload)
        if seal.body_hash is not None:
            body_hash = compute_sha256_digest({
                "job": seal.job_snapshot, "profile": seal.profile_snapshot,
                "options": seal.options, "recipe": seal.recipe, "availability": seal.availability_check,
            })
            if body_hash != seal.body_hash:
                return None, frozen_input_corrupt_error(manifest_id)
            expected_seal_hash_payload["body_hash"] = body_hash
            recomputed_hash = compute_sha256_digest(expected_seal_hash_payload)
        if recomputed_hash != seal.seal_hash:
            return None, frozen_input_corrupt_error(
                manifest_id,
                message=f"Seal integrity violation for manifest {manifest_id}",
            )

        return seal.manifest.model_copy(deep=True), None

    def build_context(
        self,
        manifest: FreezeManifest,
        context_op_id: str,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Build or retrieve context bundle strictly using frozen snapshots."""
        seal = self.engine.generation_inputs.get_seal_by_manifest_id(manifest.manifest_id)
        if seal is None:
            # Fallback search by canonical_job_id or snapshot_refs
            seal_ref = manifest.snapshot_refs.get("seal_id")
            if seal_ref:
                for s in self.engine.generation_inputs.list_context_receipts():
                    pass
            return None, frozen_input_missing_error(manifest.manifest_id)

        bundle, err = self.context_assembler.assemble_context(seal, context_op_id)
        if err or bundle is None:
            return None, err

        return bundle.model_copy(deep=True), None

    def inspect_preflight(
        self,
        request_id: uuid.UUID,
    ) -> PreflightReceipt | None:
        """Inspect durable preflight audit receipt without worker or Salesforce."""
        return self.engine.generation_inputs.get_preflight_receipt(request_id)

    def reopen_context(
        self,
        receipt_id: uuid.UUID,
    ) -> tuple[FrozenContextReceipt | None, ClassifiedError | None]:
        """Retrieve complete context selection result for downstream consumer (GEN-03)."""
        receipt = self.engine.generation_inputs.get_context_receipt(receipt_id)
        if receipt is None:
            return None, frozen_input_missing_error(str(receipt_id))
        return receipt.model_copy(deep=True), None

    def get_seal(
        self,
        request_id: uuid.UUID,
    ) -> tuple[FrozenSeal | None, ClassifiedError | None]:
        """Retrieve complete frozen seal including all snapshots."""
        seal = self.engine.generation_inputs.get_seal_by_request_id(request_id)
        if seal is None:
            return None, frozen_input_missing_error(str(request_id))
        return seal.model_copy(deep=True), None

    def get_context_receipt_by_request(
        self,
        request_id: uuid.UUID,
    ) -> tuple[FrozenContextReceipt | None, ClassifiedError | None]:
        """Retrieve durable context receipt by generation request UUID."""
        receipt = self.engine.generation_inputs.get_context_receipt_by_request_id(request_id)
        if receipt is None:
            return None, frozen_input_missing_error(str(request_id))
        return receipt.model_copy(deep=True), None

