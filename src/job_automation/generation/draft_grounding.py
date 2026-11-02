"""Conservative excerpt admission, not a semantic-entailment validator (GEN-04)."""
from __future__ import annotations

from job_automation.contracts.draft_content import DraftReviewIssue, ProtectedSourceValue
from job_automation.generation.draft_prompts import SUBJECTIVE


def admit(proposal, seal, context, recipe):
    facts = {f.fact_id: f for f in context.result.bundle.ordered_facts}
    values = []
    seen_headings = set()
    last_heading = -1
    for section in proposal.sections:
        if section.heading_key not in recipe.heading_keys or section.heading_key in seen_headings:
            raise ValueError("draft_grounding_failed")
        seen_headings.add(section.heading_key)
        position = recipe.heading_keys.index(section.heading_key)
        if position <= last_heading:
            raise ValueError("draft_grounding_failed")
        last_heading = position
    for claim in proposal.claims:
        ref = claim.evidence_reference
        if ref.source_kind == "candidate":
            fact = facts.get(ref.fact_id)
            if fact is None or ref.profile_version != seal.profile_snapshot.profile_version or seal.options.purpose not in fact.allowed_uses:
                raise ValueError("draft_grounding_failed")
            if claim.source_field not in ("title", "organization", "start_date", "end_date", "skills", "metrics", "claims"):
                raise ValueError("draft_grounding_failed")
            original = getattr(fact, claim.source_field)
            selected = original
            if isinstance(original, list):
                if claim.source_index is None or claim.source_index >= len(original):
                    raise ValueError("draft_grounding_failed")
                selected = original[claim.source_index]
            elif claim.source_index is not None:
                raise ValueError("draft_grounding_failed")
            if hasattr(selected, "value"):
                selected = selected.value
            # Existence of the UUID does NOT justify an arbitrary rewritten assertion.
            if not isinstance(selected, str) or claim.text != selected:
                raise ValueError("draft_grounding_failed")
        else:
            if ref.posting_revision != seal.job_snapshot.posting_revision_hash or claim.source_field != ref.field_path or claim.source_index is not None:
                raise ValueError("draft_grounding_failed")
            if ref.field_path not in ("description_clean", "title", "company_name_hint"):
                raise ValueError("draft_grounding_failed")
            original = getattr(seal.job_snapshot.normalized_posting, ref.field_path)
            if not isinstance(original, str) or not original:
                raise ValueError("draft_grounding_failed")
            quote = ref.quotation
            if quote is not None and (not quote.strip() or quote not in original):
                raise ValueError("draft_grounding_failed")
            if ref.source_span is not None:
                span = ref.source_span
                if span.end > len(original):
                    raise ValueError("draft_grounding_failed")
                excerpt = original[span.start:span.end]
                if quote is not None and quote != excerpt:
                    raise ValueError("draft_grounding_failed")
                quote = excerpt
            if claim.text != quote:
                raise ValueError("draft_grounding_failed")
        # Do not carry executable markup to future renderers, even from an approved source.
        if any(c in claim.text for c in ("<", ">", "\x00")):
            raise ValueError("draft_grounding_failed")
        values.append(ProtectedSourceValue(claim_id=claim.claim_id, source_field=claim.source_field,
                                          original_value=original, evidence_reference=ref))
    for block in proposal.subjective_blocks:
        if block.text not in SUBJECTIVE[recipe.target_language]:
            raise ValueError("draft_grounding_failed")
    issues = [
        DraftReviewIssue(code="semantic_review_required", message="Source references and excerpts do not establish truthful attribution, completeness, or semantic suitability. GEN-04 and human review remain pending.", uncertainty_kind="semantic_review", affected_ids=[c.claim_id for c in proposal.claims]),
        DraftReviewIssue(code="candidate_identity_missing", message="C01 supplies no dedicated candidate name or contact data; identity is omitted.", uncertainty_kind="source_unknown"),
        DraftReviewIssue(code="source_language_preserved", message="Factual excerpts retain original language; headings and subjective phrases use the requested language. Factual translation requires later review.", uncertainty_kind="translation"),
    ]
    if proposal.subjective_blocks:
        issues.append(DraftReviewIssue(code="subjective_review_required", message="Generated motivation is proposed wording, not a confirmed candidate preference.", uncertainty_kind="subjective", affected_ids=[b.block_id for b in proposal.subjective_blocks]))
    # Safe fixed message; original warning strings remain in the protected frozen receipt.
    warnings = set(seal.manifest.warnings + seal.availability_check.warnings + context.warnings + context.result.bundle.warnings)
    if context.result.trace:
        warnings.update(context.result.trace.warnings)
    if warnings:
        issues.append(DraftReviewIssue(code="upstream_warnings_present", message=f"Frozen input/context receipts contain {len(warnings)} upstream warnings; inspect those receipts before use. Retrieval omissions do not establish absent candidate skills.", uncertainty_kind="upstream"))
        issues.extend(DraftReviewIssue(code="upstream_warning", message="Preserved source/context warning; inspect its frozen receipt.", uncertainty_kind="upstream", upstream_warning=warning) for warning in sorted(warnings))
    if any(c.claim_subject == "job" for c in proposal.claims):
        issues.append(DraftReviewIssue(code="posting_attribution_required", message="Job excerpts are attributed to the posting; preserve tentative wording and review source uncertainty.", uncertainty_kind="source_uncertainty", affected_ids=[c.claim_id for c in proposal.claims if c.claim_subject == "job"]))
    return values, issues
