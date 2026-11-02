"""Document structure, required sections, and catalog compliance (GEN-04-S04)."""
from __future__ import annotations

from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.generation.draft_prompts import HEADINGS, SUBJECTIVE
from job_automation.generation.validation_records import (
    DocumentValidationIssue,
    get_content_requirements,
)


def validate_sections_and_structure(
    draft: DraftDocumentV2,
    source_map: dict[str, Any],
) -> list[DocumentValidationIssue]:
    """Validate document structure against pinned supplemental content requirements."""
    issues: list[DocumentValidationIssue] = []

    reqs = get_content_requirements(draft.template_id, draft.document_type)
    if reqs is None:
        issues.append(
            DocumentValidationIssue(
                code="unsupported_content_policy",
                severity="fatal",
                message=f"No pinned content requirements policy for template '{draft.template_id}' and type '{draft.document_type.value}'",
                suggested_action="Configure a versioned ValidationContentRequirements policy",
            )
        )
        return issues

    # 1. Section presence, uniqueness, order, and allowed set
    seen_headings = set()
    last_position = -1
    draft_headings = [s.heading_key for s in draft.sections]

    # Required sections check
    for req in reqs.required_sections:
        if req not in draft_headings:
            issues.append(
                DocumentValidationIssue(
                    code="missing_required_section",
                    severity="fatal",
                    message=f"Required section '{req}' is missing from document",
                    suggested_action=f"Include the required '{req}' section for {draft.document_type.value}",
                )
            )

    allowed_set = set(reqs.required_sections) | set(reqs.allowed_optional_sections)

    for section in draft.sections:
        sid = section.section_id
        hkey = section.heading_key

        # Allowed check
        if hkey not in allowed_set:
            issues.append(
                DocumentValidationIssue(
                    code="unexpected_section",
                    severity="fatal",
                    message=f"Section '{hkey}' is not allowed for template '{draft.template_id}' and document type '{draft.document_type.value}'",
                    section_id=sid,
                )
            )

        # Uniqueness
        if hkey in seen_headings:
            issues.append(
                DocumentValidationIssue(
                    code="duplicate_section",
                    severity="fatal",
                    message=f"Duplicate section with heading key '{hkey}' detected",
                    section_id=sid,
                )
            )
        seen_headings.add(hkey)

        # Order
        if hkey in reqs.allowed_section_order:
            pos = reqs.allowed_section_order.index(hkey)
            if pos <= last_position:
                issues.append(
                    DocumentValidationIssue(
                        code="section_order_invalid",
                        severity="fatal",
                        message=f"Section '{hkey}' violates allowed order {reqs.allowed_section_order}",
                        section_id=sid,
                    )
                )
            last_position = pos

        # Non-empty section
        all_section_claim_ids = list(section.claim_ids)
        all_section_subj_ids = list(section.subjective_ids)
        for entry in section.entries:
            all_section_claim_ids.extend(entry.claim_ids)
            all_section_subj_ids.extend(entry.subjective_ids)

        if not all_section_claim_ids and not all_section_subj_ids:
            issues.append(
                DocumentValidationIssue(
                    code="empty_section",
                    severity="fatal",
                    message=f"Section '{hkey}' has no content (no claims or subjective blocks)",
                    section_id=sid,
                )
            )

        # Check required 'experience' section contains candidate evidence
        if hkey == "experience":
            claims_by_id = {c.claim_id: c for c in draft.claims}
            cand_claims = [
                claims_by_id[cid]
                for cid in all_section_claim_ids
                if cid in claims_by_id and claims_by_id[cid].claim_subject == "candidate"
            ]
            if not cand_claims:
                issues.append(
                    DocumentValidationIssue(
                        code="experience_lacks_candidate_evidence",
                        severity="fatal",
                        message="Required 'experience' section contains no candidate factual claims",
                        section_id=sid,
                        suggested_action="Experience section must ground in candidate employment/role evidence",
                    )
                )

        # Check required 'closing' section has nonblank content
        if hkey == "closing":
            if not all_section_claim_ids and not all_section_subj_ids:
                issues.append(
                    DocumentValidationIssue(
                        code="closing_section_empty",
                        severity="fatal",
                        message="Closing section requires nonblank content or closing phrasing",
                        section_id=sid,
                    )
                )

        # 2. Localized Headings verification
        expected_catalog = HEADINGS.get(draft.target_language, {})
        expected_heading = expected_catalog.get(hkey)
        actual_heading = draft.headings.get(sid)
        if actual_heading != expected_heading:
            issues.append(
                DocumentValidationIssue(
                    code="heading_invalid",
                    severity="fatal",
                    message=f"Section heading '{actual_heading}' does not match catalog heading '{expected_heading}' for language '{draft.target_language}'",
                    section_id=sid,
                )
            )

    # 3. Subjective Blocks verification
    allowed_subj = SUBJECTIVE.get(draft.target_language, [])
    for block in draft.subjective_blocks:
        if block.text not in allowed_subj:
            issues.append(
                DocumentValidationIssue(
                    code="subjective_text_invalid",
                    severity="fatal",
                    message=f"Subjective block text '{block.text}' is not in approved phrase catalog for language '{draft.target_language}'",
                    block_id=block.block_id,
                    suggested_action="Use strictly cataloged subjective phrasing",
                )
            )

    return issues

