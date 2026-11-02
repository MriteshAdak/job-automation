"""Title, employer, and entity identity validation (GEN-04-S03)."""
from __future__ import annotations

from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.generation.validation_records import DocumentValidationIssue


def validate_values(
    draft: DraftDocumentV2,
    source_map: dict[str, Any],
    seal: Any,
) -> list[DocumentValidationIssue]:
    """Validate titles, organizations, credential identities, and role distinctions."""
    issues: list[DocumentValidationIssue] = []
    resolved_claims = source_map.get("claims", {})

    target_title = getattr(seal.job_snapshot.normalized_posting, "title", "")
    target_company = getattr(seal.job_snapshot.normalized_posting, "company_name_hint", "")

    # Build map of claim_id to section heading_key
    claim_to_section: dict[str, str] = {}
    for s in draft.sections:
        for cid in s.claim_ids:
            claim_to_section[cid] = s.heading_key
        for entry in s.entries:
            for cid in entry.claim_ids:
                claim_to_section[cid] = s.heading_key

    for claim in draft.claims:
        cid = claim.claim_id
        resolved = resolved_claims.get(cid)
        if not resolved:
            continue

        if claim.claim_subject == "candidate":
            fact = resolved.get("fact")
            if not fact:
                continue

            # Title or Organization exact extraction
            if claim.source_field in ("title", "organization"):
                orig_val = getattr(fact, claim.source_field, None)
                if not isinstance(orig_val, str) or claim.text != orig_val:
                    issues.append(
                        DocumentValidationIssue(
                            code=f"{claim.source_field}_altered",
                            severity="fatal",
                            message=f"Candidate {claim.source_field} '{claim.text}' does not match frozen source '{orig_val}'",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=claim.evidence_reference,
                            suggested_action=f"Preserve exact source {claim.source_field} without rewrite or translation",
                        )
                    )

            # Degree vs Role confusion:
            # If claim is in an 'education' section and asserts a title, the fact must be an education fact
            section_key = claim_to_section.get(cid)
            if section_key == "education" and claim.source_field == "title":
                fact_kind = getattr(fact, "kind", None)
                if fact_kind not in ("education", "certification", "degree"):
                    issues.append(
                        DocumentValidationIssue(
                            code="credential_role_confusion",
                            severity="fatal",
                            message=f"Education section cites a '{fact_kind}' fact title as a credential/degree",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=claim.evidence_reference,
                            suggested_action="Education entries must cite education or certification facts",
                        )
                    )

            # Candidate / Target role or employer swap:
            # Candidate history cannot claim the target vacancy title as past role if it's not the candidate's fact title
            if claim.source_field == "title" and target_title:
                # If claim text matches target posting title, make sure candidate fact title actually equals target_title
                cand_title = getattr(fact, "title", "")
                if claim.text == target_title and cand_title != target_title:
                    issues.append(
                        DocumentValidationIssue(
                            code="target_role_swap",
                            severity="fatal",
                            message="Candidate role title swapped with target job posting title",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=claim.evidence_reference,
                        )
                    )

            if claim.source_field == "organization" and target_company:
                cand_org = getattr(fact, "organization", "")
                if claim.text == target_company and cand_org != target_company:
                    issues.append(
                        DocumentValidationIssue(
                            code="target_employer_swap",
                            severity="fatal",
                            message="Candidate employer swapped with target company name",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=claim.evidence_reference,
                        )
                    )

    return issues

