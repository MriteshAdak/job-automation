"""Input resolution for canonical jobs, approved profiles, options, and context recipes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.context.preparation import ProfileContextPreparer
from job_automation.context.retrieval_settings import DEFAULT_RETRIEVAL_SETTINGS
from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.retrieval_index import IndexManifest
from job_automation.generation.input_errors import (
    job_snapshot_mismatch_error,
    profile_unapproved_error,
)
from job_automation.generation.input_records import (
    FrozenContextRecipe,
    FrozenGenerationOptions,
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
    GenerationInputSettings,
    compute_sha256_digest,
)
from job_automation.generation.request_mapping import compute_options_digest
from job_automation.identity.hashing import compute_revision_content_hash

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class InputResolver:
    """Resolves and validates exact, immutable component inputs prior to sealing."""

    def __init__(
        self,
        engine: StorageEngine,
        settings: GenerationInputSettings | None = None,
        recipe_provider: Any = None,
    ) -> None:
        self.engine = engine
        self.settings = settings or GenerationInputSettings()
        self.recipe_provider = recipe_provider

    def resolve_inputs(
        self,
        request: GenerationRequest,
        freeze_op_id: str,
    ) -> tuple[
        tuple[FrozenJobSnapshot, FrozenProfileSnapshot, FrozenGenerationOptions, FrozenContextRecipe] | None,
        ClassifiedError | None,
    ]:
        """Resolve all prerequisite inputs for a GenerationRequest."""
        # 1. Resolve candidate ID and current approved ProfileSnapshot (C01)
        candidate_id = self.settings.candidate_id
        if candidate_id is None:
            # Query default candidate from profile_current
            curr_ver = self.engine.profiles.get_current_version()
            if curr_ver is None:
                return None, profile_unapproved_error(message="No current approved profile found in storage")
            # Find candidate_id associated with current version
            history = self.engine.profiles.get_version_history()
            match = next((h for h in history if h.profile_version == curr_ver), None)
            if match is None:
                return None, profile_unapproved_error(message=f"Current profile version '{curr_ver}' has no history record")
            candidate_id = match.candidate_id

        snapshot = self.engine.profiles.get_current_snapshot(candidate_id)
        if snapshot is None:
            return None, profile_unapproved_error(candidate_id)

        # 2. Derive purpose and compute purpose-specific eligibility
        purpose = "cv" if request.document_type == DocumentType.CV else "cover_letter"

        history = self.engine.profiles.get_version_history(candidate_id)
        version_rec = next((h for h in history if h.profile_version == snapshot.profile_version), None)
        approved_by = version_rec.approved_by if version_rec else "candidate"
        approved_at = version_rec.approved_at if version_rec else datetime.now(timezone.utc)
        notes = version_rec.notes if version_rec else None

        preparer = ProfileContextPreparer()
        prepared = preparer.prepare_context(snapshot, purpose=purpose)
        eligible_fact_ids = list(prepared.eligible_fact_ids)
        explicit_mandatory_fact_ids = list(prepared.mandatory_fact_ids)

        profile_digest_payload = {
            "candidate_id": str(candidate_id),
            "profile_version": snapshot.profile_version,
            "purpose": purpose,
            "eligible_fact_ids": [str(fid) for fid in sorted(eligible_fact_ids)],
            "approved_by": approved_by,
            "approved_at": approved_at.isoformat(),
        }
        profile_digest = compute_sha256_digest(profile_digest_payload)

        frozen_profile = FrozenProfileSnapshot(
            candidate_id=candidate_id,
            profile_version=snapshot.profile_version,
            snapshot=snapshot,
            approved_by=approved_by,
            approved_at=approved_at,
            notes=notes,
            purpose=purpose,
            eligible_fact_ids=eligible_fact_ids,
            explicit_mandatory_fact_ids=explicit_mandatory_fact_ids,
            snapshot_digest=profile_digest,
        )

        # 3. Resolve target CanonicalJob (C07) and current NormalizedPosting (C06)
        job = self.engine.canonical_jobs.get_canonical_job(request.canonical_job_id)
        if job is None:
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Canonical job {request.canonical_job_id} not found",
                details={"reason_code": "job_not_found"},
            )

        revisions = self.engine.canonical_jobs.get_revisions(request.canonical_job_id)
        current_rev = next((r for r in revisions if r.revision_id == job.current_revision_id), None)
        if current_rev is None and revisions:
            current_rev = revisions[-1]

        if current_rev is None:
            return None, job_snapshot_mismatch_error(
                request.canonical_job_id,
                f"No revisions found for canonical job {request.canonical_job_id}",
            )

        normalized_posting = self.engine.canonical_jobs.get_normalized_posting(current_rev.source_key)
        if normalized_posting is None:
            return None, job_snapshot_mismatch_error(
                request.canonical_job_id,
                f"Normalized posting not found for source key {current_rev.source_key}",
            )

        # Verify material content hash
        material_hash = compute_revision_content_hash(normalized_posting)
        if current_rev.content_hash != material_hash:
            return None, job_snapshot_mismatch_error(
                request.canonical_job_id,
                f"Job content hash mismatch: revision declares '{current_rev.content_hash}', "
                f"computed normalized material hash is '{material_hash}'",
            )

        job_digest_payload = {
            "canonical_job_id": str(job.canonical_job_id),
            "posting_revision_id": str(current_rev.revision_id),
            "posting_revision_hash": current_rev.content_hash,
            "raw_content_hash": (
                normalized_posting.raw_content_hash
                if isinstance(normalized_posting.raw_content_hash, str)
                else getattr(normalized_posting.raw_content_hash, "value", str(normalized_posting.raw_content_hash))
            ),
            "source_key": current_rev.source_key.model_dump(mode="json"),
            "title": normalized_posting.title,
            "company_name": job.company_name,
        }
        job_digest = compute_sha256_digest(job_digest_payload)

        raw_ref_val = normalized_posting.raw_reference
        raw_ref_str = (
            raw_ref_val
            if isinstance(raw_ref_val, str)
            else (getattr(raw_ref_val, "value", str(raw_ref_val)) if raw_ref_val else None)
        )

        frozen_job = FrozenJobSnapshot(
            canonical_job_id=job.canonical_job_id,
            company_name=job.company_name,
            posting_revision_id=str(current_rev.revision_id),
            posting_revision_hash=current_rev.content_hash,
            raw_content_hash=(
                normalized_posting.raw_content_hash
                if isinstance(normalized_posting.raw_content_hash, str)
                else getattr(normalized_posting.raw_content_hash, "value", str(normalized_posting.raw_content_hash))
            ),
            source_key=current_rev.source_key,
            normalized_posting=normalized_posting,
            raw_reference=raw_ref_str,
            source_url=getattr(normalized_posting, "source_url", None),
            application_url=getattr(normalized_posting, "application_url", None),
            observed_at=normalized_posting.observed_at,
            first_seen_at=job.first_seen_at,
            last_seen_at=job.last_seen_at,
            snapshot_digest=job_digest,
        )

        # 4. Canonicalize options
        strict_override = request.allow_unavailable_job is True
        override_prov = f"candidate_request:{request.request_id}" if strict_override else None
        now_utc = datetime.now(timezone.utc)

        opts_dict: dict[str, Any] = {
            "canonical_job_id": str(request.canonical_job_id),
            "document_type": request.document_type.value,
            "target_language": request.target_language,
            "template_id": request.template_id,
            "context_strategy": request.context_strategy.value,
            "allow_unavailable_job": strict_override,
        }
        opts_digest = compute_options_digest(opts_dict)

        frozen_options = FrozenGenerationOptions(
            document_type=request.document_type,
            purpose=purpose,
            target_language=request.target_language,
            template_id=request.template_id,
            template_version=self.settings.default_template_version,
            context_strategy=request.context_strategy,
            allow_unavailable_job=strict_override,
            override_provenance=override_prov,
            override_timestamp=now_utc if strict_override else None,
            options_digest=opts_digest,
        )

        # 5. Build context recipe
        requirements: list[str] = []
        if normalized_posting.description_clean:
            # Deterministic requirement extraction / line splitting
            lines = [line.strip("- *• \t\r") for line in normalized_posting.description_clean.splitlines() if line.strip()]
            requirements = [ln for ln in lines if len(ln) > 10][:15]
        if not requirements:
            requirements = [normalized_posting.title]

        req_hash = compute_sha256_digest(requirements)
        instruction_text = (
            self.settings.default_instruction_text_cv
            if request.document_type == DocumentType.CV
            else self.settings.default_instruction_text_cover_letter
        )

        recipe_payload = {
            "purpose": purpose,
            "requirements_extraction_hash": req_hash,
            "model_identifier": self.settings.default_model_identifier,
            "context_limit": self.settings.default_context_limit,
            "output_reserve": self.settings.default_output_reserve,
            "safety_allowance": self.settings.default_safety_allowance,
            "strategy": request.context_strategy.value,
        }
        recipe_digest = compute_sha256_digest(recipe_payload)

        emb_config = self.settings.embedding_config
        if emb_config is None and request.context_strategy == ContextStrategy.RAG:
            active_gen = self.engine.context_indexes.get_active_generation(candidate_id, purpose)
            if active_gen and active_gen.get("manifest_json"):
                idx_manifest = IndexManifest.model_validate_json(active_gen["manifest_json"])
                emb_config = idx_manifest.embedding_configuration

        frozen_recipe = FrozenContextRecipe(
            recipe_id=f"recipe:{request.request_id}:{purpose}",
            instruction_text=instruction_text,
            requirements=requirements,
            requirements_extraction_hash=req_hash,
            model_identifier=self.settings.default_model_identifier,
            context_limit=self.settings.default_context_limit,
            output_reserve=self.settings.default_output_reserve,
            safety_allowance=self.settings.default_safety_allowance,
            require_exact_measurement=self.settings.require_exact_measurement,
            retrieval_settings=self.settings.retrieval_settings if request.context_strategy == ContextStrategy.RAG else None,
            embedding_config=emb_config if request.context_strategy == ContextStrategy.RAG else None,
            recipe_digest=recipe_digest,
        )

        if self.recipe_provider is not None:
            try:
                frozen_options, frozen_recipe = self.recipe_provider.configure(
                    request, frozen_job, frozen_options, frozen_recipe,
                )
            except ValueError:
                return None, ClassifiedError.from_category(
                    ErrorCategory.UNSUPPORTED_INPUT, "Draft recipe options are unsupported",
                    details={"reason_code": "draft_option_unsupported"},
                )
        return (frozen_job, frozen_profile, frozen_options, frozen_recipe), None
