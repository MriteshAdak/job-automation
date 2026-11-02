"""Binding and provenance verification against frozen resources (GEN-04-S02)."""
from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.generation.draft_inputs import verify_binding
from job_automation.generation.draft_prompts import DraftRecipe
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.generation.validation_records import (
    DocumentValidationIssue,
    DocumentValidationSettings,
    ValidationInputBinding,
)


def verify_validation_binding(
    inputs: Any,
    request_id: uuid.UUID,
    draft: DraftDocumentV2,
    rule_settings: DocumentValidationSettings,
    draft_repository: Any = None,
) -> tuple[ValidationInputBinding | None, list[DocumentValidationIssue]]:
    """Verify draft against request-owned frozen seal, context receipt, and binding."""
    issues: list[DocumentValidationIssue] = []

    # 1. Standalone verification of frozen inputs using existing pure verification path
    try:
        seal, context_receipt, recipe, binding_hash = verify_binding(inputs, request_id)
    except Exception as exc:
        issues.append(
            DocumentValidationIssue(
                code="frozen_binding_corrupt",
                severity="fatal",
                message=f"Frozen inputs or binding verification failed: {exc}",
                suggested_action="Check frozen seal and context receipt integrity in storage",
            )
        )
        return None, issues

    draft_hash = compute_sha256_digest(draft)

    # 2. Compare draft provenance and frozen metadata
    prov = draft.provenance
    mismatches = []
    if draft.request_id != request_id:
        mismatches.append(f"request_id mismatch: {draft.request_id} != {request_id}")
    if prov.seal_id != seal.seal_id:
        mismatches.append(f"seal_id mismatch: {prov.seal_id} != {seal.seal_id}")
    if prov.seal_hash != seal.seal_hash:
        mismatches.append("seal_hash mismatch")
    if prov.binding_hash != binding_hash:
        mismatches.append("binding_hash mismatch")
    if prov.context_receipt_id != context_receipt.receipt_id:
        mismatches.append("context_receipt_id mismatch")
    if prov.context_hash != compute_sha256_digest(context_receipt):
        mismatches.append("context_hash mismatch")
    if prov.recipe_hash != recipe.recipe_hash:
        mismatches.append("recipe_hash mismatch")
    if prov.prompt_version != recipe.prompt_version:
        mismatches.append("prompt_version mismatch")
    if prov.schema_digest != recipe.proposal_schema_digest:
        mismatches.append("schema_digest mismatch")

    # Frozen input versions
    frozen = draft.frozen_inputs
    if frozen.posting_revision != seal.job_snapshot.posting_revision_hash:
        mismatches.append("frozen posting_revision mismatch")
    if frozen.profile_version != seal.profile_snapshot.profile_version:
        mismatches.append("frozen profile_version mismatch")
    if frozen.policy_version != seal.manifest.policy_version:
        mismatches.append("frozen policy_version mismatch")
    if frozen.template_version != recipe.template_version:
        mismatches.append("frozen template_version mismatch")

    # Document options
    if draft.document_type != seal.options.document_type:
        mismatches.append("document_type mismatch")
    if draft.target_language != seal.options.target_language:
        mismatches.append("target_language mismatch")
    if draft.template_id != seal.options.template_id:
        mismatches.append("template_id mismatch")
    if draft.template_version != recipe.template_version:
        mismatches.append("template_version mismatch")
    if draft.template_content_digest != seal.options.template_content_digest:
        mismatches.append("template_content_digest mismatch")

    # 3. Verify against draft receipt if available in repository
    receipt_hash = ""
    if draft_repository is not None:
        try:
            saved_receipt = draft_repository.get_by_request(request_id)
            if saved_receipt is not None:
                receipt_hash = compute_sha256_digest(saved_receipt)
                if saved_receipt.draft is not None:
                    if compute_sha256_digest(saved_receipt.draft) != draft_hash:
                        mismatches.append("draft content differs from committed draft receipt")
                if saved_receipt.binding_hash != binding_hash:
                    mismatches.append("receipt binding_hash mismatch")
        except Exception as exc:
            issues.append(
                DocumentValidationIssue(
                    code="draft_receipt_corrupt",
                    severity="fatal",
                    message=f"Draft receipt lookup error: {exc}",
                )
            )

    if mismatches:
        for m in mismatches:
            issues.append(
                DocumentValidationIssue(
                    code="provenance_binding_mismatch",
                    severity="fatal",
                    message=f"Draft provenance mismatch with frozen inputs: {m}",
                    suggested_action="Ensure draft was generated for this exact frozen request and seal",
                )
            )

    binding = ValidationInputBinding(
        request_id=request_id,
        candidate_id=seal.candidate_id,
        canonical_job_id=seal.canonical_job_id,
        draft_id=draft.draft_id,
        draft_version=draft.document_version,
        draft_schema_version=draft.schema_version,
        draft_hash=draft_hash,
        receipt_id=prov.receipt_id,
        receipt_hash=receipt_hash or prov.receipt_id.hex,
        seal_id=seal.seal_id,
        seal_hash=seal.seal_hash,
        manifest_id=seal.manifest.manifest_id,
        manifest_hash=seal.manifest.manifest_hash,
        profile_version=seal.profile_snapshot.profile_version,
        profile_snapshot_digest=seal.profile_snapshot.snapshot_digest,
        posting_revision_id=seal.manifest.posting_revision_id,
        posting_revision_hash=seal.job_snapshot.posting_revision_hash,
        context_receipt_id=context_receipt.receipt_id,
        context_hash=compute_sha256_digest(context_receipt),
        admitted_fact_ids=context_receipt.result.bundle.selected_fact_ids,
        document_type=draft.document_type,
        purpose=seal.options.purpose,
        target_language=draft.target_language,
        template_id=draft.template_id,
        template_version=draft.template_version,
        template_content_digest=draft.template_content_digest,
        rule_set_id=rule_settings.rule_set_id,
        rule_set_version=rule_settings.rule_set_version,
        rule_set_digest=rule_settings.rule_set_digest,
        binding_hash=binding_hash,
    )
    return binding, issues
