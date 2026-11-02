"""Verify request-owned GEN-02 bodies without querying mutable source repositories."""
from __future__ import annotations

import json

from job_automation.context.records import JsonContextRequest
from job_automation.context.rendering import DefaultPromptRenderer
from job_automation.context.serialization import serialize_candidate_fact
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.draft_prompts import DraftRecipe, DraftRecipeProvider, FRAMING_VERSION
from job_automation.generation.input_records import compute_sha256_digest, compute_manifest_hash
from job_automation.identity.hashing import compute_revision_content_hash
from job_automation.generation.request_mapping import compute_options_digest


def verify_binding(inputs, request_id):
    seal, error = inputs.get_seal(request_id)
    if error or seal is None:
        raise ValueError("draft_dependency_missing")
    manifest, error = inputs.reopen_freeze(seal.manifest.manifest_id)
    if error or manifest != seal.manifest:
        raise ValueError("frozen_input_corrupt")
    receipt, error = inputs.get_context_receipt_by_request(request_id)
    if error or receipt is None:
        raise ValueError("draft_dependency_missing")
    reopened, error = inputs.reopen_context(receipt.receipt_id)
    if error or reopened != receipt:
        raise ValueError("frozen_input_corrupt")
    options, profile, job, context_recipe = seal.options, seal.profile_snapshot, seal.job_snapshot, seal.recipe
    if context_recipe.content_recipe_json is None or seal.body_hash is None:
        raise ValueError("recipe_unavailable")
    recipe = DraftRecipe.model_validate_json(context_recipe.content_recipe_json)
    request = GenerationRequest(
        request_id=request_id, canonical_job_id=seal.canonical_job_id,
        document_type=options.document_type, target_language=options.target_language,
        template_id=options.template_id, context_strategy=options.context_strategy,
        allow_unavailable_job=options.allow_unavailable_job, created_at=seal.sealed_at,
    )
    expected = DraftRecipeProvider(recipe.model_identifier, recipe.model_digest).make_recipe(request, job, context_recipe)
    if recipe != expected or options.generation_settings != recipe.generation_settings or options.template_content_digest != recipe.template_content_digest:
        raise ValueError("recipe_unavailable")
    if context_recipe.instruction_text != recipe.instruction_text or context_recipe.output_schema_text != recipe.output_schema_text or context_recipe.chat_template_version != FRAMING_VERSION:
        raise ValueError("recipe_unavailable")
    if context_recipe.model_identifier != recipe.model_identifier or recipe.generation_settings.get("num_predict") != recipe.output_reserve:
        raise ValueError("recipe_unavailable")
    expected_options_digest = compute_options_digest({
        "canonical_job_id": str(seal.canonical_job_id), "document_type": options.document_type.value,
        "target_language": options.target_language, "template_id": options.template_id,
        "context_strategy": options.context_strategy.value, "allow_unavailable_job": options.allow_unavailable_job,
    })
    if options.options_digest != expected_options_digest or seal.manifest.options_digest != expected_options_digest:
        raise ValueError("draft_binding_mismatch")
    if context_recipe.recipe_digest != compute_sha256_digest(context_recipe.model_dump(mode="json", exclude={"recipe_digest"})):
        raise ValueError("frozen_input_corrupt")
    body_hash = compute_sha256_digest({"job": job, "profile": profile, "options": options, "recipe": context_recipe, "availability": seal.availability_check})
    if body_hash != seal.body_hash:
        raise ValueError("frozen_input_corrupt")
    manifest_payload = seal.manifest.model_dump(mode="json", exclude={"schema_version"})
    # GEN-02 v1 hashes datetime.isoformat(), whereas Pydantic JSON uses 'Z'.
    manifest_payload["frozen_at"] = seal.manifest.frozen_at.isoformat()
    manifest_hash = compute_manifest_hash(manifest_payload)
    seal_hash = compute_sha256_digest({
        "seal_id": seal.seal_id, "request_id": str(request_id), "manifest_hash": manifest_hash,
        "job_snapshot_digest": job.snapshot_digest, "profile_snapshot_digest": profile.snapshot_digest,
        "recipe_digest": context_recipe.recipe_digest, "options_digest": options.options_digest, "body_hash": body_hash,
    })
    bundle = receipt.result.bundle
    if not all((
        seal.request_id == request_id == receipt.request_id,
        seal.candidate_id == profile.candidate_id == profile.snapshot.candidate_id == bundle.candidate_id,
        seal.canonical_job_id == job.canonical_job_id == seal.manifest.canonical_job_id,
        seal.manifest.manifest_hash == manifest_hash == receipt.manifest_hash,
        seal.seal_hash == seal_hash, receipt.manifest_id == seal.manifest.manifest_id,
        receipt.recipe_hash == context_recipe.recipe_digest,
        profile.profile_version == profile.snapshot.profile_version == bundle.profile_version == seal.manifest.profile_version,
        options.purpose == options.document_type.value == profile.purpose == bundle.purpose,
        options.context_strategy == bundle.strategy == seal.manifest.context_strategy,
        options.target_language == seal.manifest.target_language == recipe.target_language,
        options.template_id == seal.manifest.template_id == recipe.template_id,
        options.template_version == seal.manifest.template_version == recipe.template_version,
        job.posting_revision_id == seal.manifest.posting_revision_id,
        job.posting_revision_hash == seal.manifest.posting_revision_hash == bundle.posting_revision == compute_revision_content_hash(job.normalized_posting),
        profile.snapshot.approval_metadata.is_approved,
        job.source_key == job.normalized_posting.source_key,
        job.raw_content_hash == job.normalized_posting.raw_content_hash,
        seal.availability_check.canonical_job_id == seal.canonical_job_id,
        seal.manifest.allow_unavailable_job == options.allow_unavailable_job == seal.availability_check.allow_unavailable_job,
    )):
        raise ValueError("draft_binding_mismatch")
    expected_refs = {"job_snapshot": job.snapshot_digest, "profile_snapshot": profile.snapshot_digest,
                     "recipe": context_recipe.recipe_digest, "options": options.options_digest,
                     "availability_check": seal.availability_check.check_digest}
    if any(seal.manifest.snapshot_refs.get(key) != value for key, value in expected_refs.items()):
        raise ValueError("draft_binding_mismatch")
    facts = {f.fact_id: f for f in profile.snapshot.evidence_records}
    selected = bundle.selected_fact_ids
    if len(selected) != len(set(selected)) or len(selected) != len(bundle.ordered_facts) or set(selected) != {f.fact_id for f in bundle.ordered_facts}:
        raise ValueError("draft_binding_mismatch")
    for fact in bundle.ordered_facts:
        if facts.get(fact.fact_id) != fact or fact.fact_id not in profile.eligible_fact_ids or options.purpose not in fact.allowed_uses:
            raise ValueError("draft_binding_mismatch")
    if options.context_strategy == ContextStrategy.JSON and set(selected) != set(profile.eligible_fact_ids):
        raise ValueError("draft_binding_mismatch")
    if options.context_strategy == ContextStrategy.RAG and (seal.index_pin_id is None or seal.pinned_index_generation_id is None):
        raise ValueError("draft_binding_mismatch")
    rendered = receipt.result.rendered_prompt
    result_hash = compute_sha256_digest({
        "construction_fingerprint": receipt.result.construction_fingerprint,
        "manifest_hash": manifest_hash, "recipe_hash": context_recipe.recipe_digest, "prompt_text": rendered.full_prompt,
    })
    if result_hash != receipt.result_hash or rendered.render_template_version != FRAMING_VERSION:
        raise ValueError("frozen_input_corrupt")
    projection = json.loads(rendered.candidate_json.split("CANDIDATE_JSON_DATA\n", 1)[1])
    if projection["facts"] != [serialize_candidate_fact(f) for f in bundle.ordered_facts]:
        raise ValueError("draft_binding_mismatch")
    if projection["candidate_id"] != str(seal.candidate_id) or projection["profile_version"] != profile.profile_version or projection["purpose"] != options.purpose:
        raise ValueError("draft_binding_mismatch")
    if projection["explicit_eligibility"] != profile.snapshot.explicit_eligibility.model_dump(mode="json"):
        raise ValueError("draft_binding_mismatch")
    render_request = JsonContextRequest(
        snapshot=profile.snapshot, purpose=options.purpose, canonical_job_id=seal.canonical_job_id,
        posting_revision=job.posting_revision_hash, job_content=job.normalized_posting,
        requirements=context_recipe.requirements, instruction_text=recipe.instruction_text,
        output_schema_text=recipe.output_schema_text, model_identifier=recipe.model_identifier,
        context_limit=recipe.context_limit, chat_template_version=FRAMING_VERSION,
    )
    if DefaultPromptRenderer().render(render_request, json.dumps(projection)) != rendered:
        raise ValueError("frozen_input_corrupt")
    report = bundle.budget_report
    if (report is None or not report.fits or report.total_demand > recipe.context_limit
            or report.effective_window != recipe.context_limit
            or report.total_demand != report.total_input_tokens + recipe.output_reserve + recipe.safety_allowance
            or report.output_reserve != recipe.output_reserve or report.safety_allowance != recipe.safety_allowance
            or (recipe.require_exact_measurement and not report.is_exact)):
        raise ValueError("draft_context_budget")
    binding_hash = compute_sha256_digest({"seal": seal, "context": receipt, "recipe_hash": recipe.recipe_hash})
    return seal, receipt, recipe, binding_hash
