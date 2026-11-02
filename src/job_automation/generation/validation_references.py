"""Candidate and job evidence resolution and citation verification (GEN-04-S02)."""
from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2, ProtectedSourceValue
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference
from job_automation.generation.validation_records import DocumentValidationIssue


def resolve_and_verify_references(
    draft: DraftDocumentV2,
    seal: Any,
    context_receipt: Any,
) -> tuple[dict[str, Any], list[DocumentValidationIssue]]:
    """Resolve and verify all claims against frozen candidate profile and job posting.

    Returns a resolved source map:
        {
            "claims": {claim_id: resolved_source_info},
            "facts_by_id": facts_by_id,
            "protected_values": pv_by_claim_id,
        }
    and a list of validation issues.
    """
    issues: list[DocumentValidationIssue] = []

    profile_snapshot = seal.profile_snapshot.snapshot
    candidate_id = profile_snapshot.candidate_id
    profile_version = profile_snapshot.profile_version
    purpose = seal.options.purpose

    facts_by_id = {f.fact_id: f for f in profile_snapshot.evidence_records}
    admitted_ids = set(context_receipt.result.bundle.selected_fact_ids)
    eligible_ids = set(seal.profile_snapshot.eligible_fact_ids)

    job_snapshot = seal.job_snapshot
    posting_revision_hash = job_snapshot.posting_revision_hash
    normalized_posting = job_snapshot.normalized_posting

    pv_by_claim_id = {pv.claim_id: pv for pv in draft.protected_values}
    resolved_claims: dict[str, Any] = {}

    for claim in draft.claims:
        cid = claim.claim_id
        ref = claim.evidence_reference

        # Check for unsafe markup / delimiters
        if any(c in claim.text for c in ("<", ">", "\x00")):
            issues.append(
                DocumentValidationIssue(
                    code="unsafe_claim_characters",
                    severity="fatal",
                    message="Claim text contains prohibited markup or null bytes",
                    claim_id=cid,
                    source_field=claim.source_field,
                    evidence_reference=ref,
                )
            )

        # Protected source value existence
        pv = pv_by_claim_id.get(cid)
        if pv is None:
            issues.append(
                DocumentValidationIssue(
                    code="protected_value_missing",
                    severity="fatal",
                    message="Claim lacks a corresponding protected source value record",
                    claim_id=cid,
                    source_field=claim.source_field,
                    evidence_reference=ref,
                )
            )

        # ---------------------------------------------------------------------
        # Candidate Claim Verification
        # ---------------------------------------------------------------------
        if claim.claim_subject == "candidate":
            if not isinstance(ref, CandidateEvidenceReference) or ref.source_kind != "candidate":
                issues.append(
                    DocumentValidationIssue(
                        code="claim_subject_mismatch",
                        severity="fatal",
                        message="Candidate claim cites non-candidate evidence",
                        claim_id=cid,
                        evidence_reference=ref,
                        suggested_action="Candidate claims must cite CandidateEvidenceReference",
                    )
                )
                continue

            # Version check
            if ref.profile_version != profile_version:
                issues.append(
                    DocumentValidationIssue(
                        code="wrong_profile_version",
                        severity="fatal",
                        message=f"Candidate reference specifies version '{ref.profile_version}', expected frozen '{profile_version}'",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )

            # Fact existence
            fact = facts_by_id.get(ref.fact_id)
            if fact is None:
                issues.append(
                    DocumentValidationIssue(
                        code="fact_not_found",
                        severity="fatal",
                        message=f"Candidate fact ID '{ref.fact_id}' not found in frozen profile snapshot",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )
                continue

            # Approval metadata check
            if not profile_snapshot.approval_metadata.is_approved:
                issues.append(
                    DocumentValidationIssue(
                        code="profile_unapproved",
                        severity="fatal",
                        message="Profile snapshot approval metadata indicates unapproved profile",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )

            # Admission check
            if ref.fact_id not in admitted_ids:
                issues.append(
                    DocumentValidationIssue(
                        code="fact_not_admitted",
                        severity="fatal",
                        message=f"Candidate fact '{ref.fact_id}' exists in profile but was not admitted into context bundle",
                        claim_id=cid,
                        evidence_reference=ref,
                        suggested_action="Only claims admitted into the frozen context bundle may be included",
                    )
                )

            # Eligibility & Purpose check
            if ref.fact_id not in eligible_ids:
                issues.append(
                    DocumentValidationIssue(
                        code="fact_ineligible",
                        severity="fatal",
                        message=f"Candidate fact '{ref.fact_id}' is not in eligible fact IDs",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )

            if purpose not in fact.allowed_uses:
                issues.append(
                    DocumentValidationIssue(
                        code="fact_purpose_unauthorized",
                        severity="fatal",
                        message=f"Candidate fact '{ref.fact_id}' is not authorized for purpose '{purpose}' (allowed: {fact.allowed_uses})",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )

            # Parent privacy check
            if getattr(fact, "parent_fact_id", None) is not None:
                parent = facts_by_id.get(fact.parent_fact_id)
                if parent is not None and purpose not in parent.allowed_uses:
                    # Child is permitted, but parent is restricted! Ensure child doesn't leak parent's title/org/dates
                    restricted_terms = [parent.title, getattr(parent, "organization", None)]
                    for rt in restricted_terms:
                        if rt and isinstance(rt, str) and rt.strip() and rt.lower() in claim.text.lower():
                            issues.append(
                                DocumentValidationIssue(
                                    code="parent_privacy_violation",
                                    severity="fatal",
                                    message=f"Child fact claim leaks restricted parent entity information ('{rt}')",
                                    claim_id=cid,
                                    evidence_reference=ref,
                                )
                            )

            # Source field and index bounds
            allowed_candidate_fields = ("title", "organization", "start_date", "end_date", "skills", "metrics", "claims")
            if claim.source_field not in allowed_candidate_fields:
                issues.append(
                    DocumentValidationIssue(
                        code="invalid_source_field",
                        severity="fatal",
                        message=f"Source field '{claim.source_field}' is not allowed for candidate claims",
                        claim_id=cid,
                        source_field=claim.source_field,
                        evidence_reference=ref,
                    )
                )
                continue

            original_field_val = getattr(fact, claim.source_field, None)
            selected_val = original_field_val

            if claim.source_field in ("skills", "metrics", "claims"):
                if not isinstance(original_field_val, list):
                    issues.append(
                        DocumentValidationIssue(
                            code="source_field_type_mismatch",
                            severity="fatal",
                            message=f"Source field '{claim.source_field}' expected to be list, got {type(original_field_val)}",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=ref,
                        )
                    )
                elif claim.source_index is None:
                    issues.append(
                        DocumentValidationIssue(
                            code="missing_source_index",
                            severity="fatal",
                            message=f"List field '{claim.source_field}' requires a source_index",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=ref,
                        )
                    )
                elif claim.source_index < 0 or claim.source_index >= len(original_field_val):
                    issues.append(
                        DocumentValidationIssue(
                            code="source_index_out_of_bounds",
                            severity="fatal",
                            message=f"source_index {claim.source_index} out of bounds for '{claim.source_field}' (length {len(original_field_val)})",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=ref,
                        )
                    )
                else:
                    selected_val = original_field_val[claim.source_index]
            else:
                if claim.source_index is not None:
                    issues.append(
                        DocumentValidationIssue(
                            code="unexpected_source_index",
                            severity="fatal",
                            message=f"Scalar field '{claim.source_field}' must not have a source_index",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=ref,
                        )
                    )

            # Protected value agreement with the full source field
            if pv is not None:
                if pv.source_field != claim.source_field or pv.evidence_reference != ref:
                    issues.append(
                        DocumentValidationIssue(
                            code="protected_value_mismatch",
                            severity="fatal",
                            message="ProtectedSourceValue source_field or reference disagrees with claim",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=ref,
                        )
                    )
                if pv.original_value != original_field_val:
                    issues.append(
                        DocumentValidationIssue(
                            code="protected_original_value_mismatch",
                            severity="fatal",
                            message="ProtectedSourceValue original_value does not match full frozen fact field",
                            claim_id=cid,
                            source_field=claim.source_field,
                            evidence_reference=ref,
                        )
                    )

            resolved_claims[cid] = {
                "subject": "candidate",
                "fact": fact,
                "field": claim.source_field,
                "original_field_val": original_field_val,
                "selected_val": selected_val,
            }

        # ---------------------------------------------------------------------
        # Job Claim Verification
        # ---------------------------------------------------------------------
        elif claim.claim_subject == "job":
            if not isinstance(ref, JobEvidenceReference) or ref.source_kind != "job":
                issues.append(
                    DocumentValidationIssue(
                        code="claim_subject_mismatch",
                        severity="fatal",
                        message="Job claim cites non-job evidence",
                        claim_id=cid,
                        evidence_reference=ref,
                        suggested_action="Job claims must cite JobEvidenceReference",
                    )
                )
                continue

            # Revision check
            if ref.posting_revision != posting_revision_hash:
                issues.append(
                    DocumentValidationIssue(
                        code="wrong_posting_revision",
                        severity="fatal",
                        message=f"Job reference revision '{ref.posting_revision}' differs from frozen '{posting_revision_hash}'",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )

            # Field path check
            allowed_job_fields = ("description_clean", "title", "company_name_hint")
            if ref.field_path not in allowed_job_fields:
                issues.append(
                    DocumentValidationIssue(
                        code="disallowed_job_field_path",
                        severity="fatal",
                        message=f"Field path '{ref.field_path}' is not in allowed job text paths",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )
                continue

            if claim.source_field != ref.field_path:
                issues.append(
                    DocumentValidationIssue(
                        code="source_field_mismatch",
                        severity="fatal",
                        message=f"Claim source_field '{claim.source_field}' disagrees with reference field_path '{ref.field_path}'",
                        claim_id=cid,
                        source_field=claim.source_field,
                        evidence_reference=ref,
                    )
                )

            if claim.source_index is not None:
                issues.append(
                    DocumentValidationIssue(
                        code="unexpected_source_index",
                        severity="fatal",
                        message="Job text claim must not specify a source_index",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )

            posting_text = getattr(normalized_posting, ref.field_path, None)
            if not isinstance(posting_text, str) or not posting_text:
                issues.append(
                    DocumentValidationIssue(
                        code="job_field_empty_or_missing",
                        severity="fatal",
                        message=f"Frozen posting text field '{ref.field_path}' is empty or missing",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )
                continue

            quote = ref.quotation
            span = ref.source_span

            if quote is None and span is None:
                issues.append(
                    DocumentValidationIssue(
                        code="missing_job_quote_and_span",
                        severity="fatal",
                        message="Job citation provides neither quotation nor source_span",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )
                continue

            expected_excerpt = None
            if quote is not None:
                if not quote.strip():
                    issues.append(
                        DocumentValidationIssue(
                            code="whitespace_job_quote",
                            severity="fatal",
                            message="Job quotation cannot be all-whitespace",
                            claim_id=cid,
                            evidence_reference=ref,
                        )
                    )
                elif quote not in posting_text:
                    issues.append(
                        DocumentValidationIssue(
                            code="job_quote_not_found",
                            severity="fatal",
                            message="Quotation not found in frozen posting text",
                            claim_id=cid,
                            evidence_reference=ref,
                        )
                    )
                expected_excerpt = quote

            if span is not None:
                if span.start < 0 or span.end > len(posting_text) or span.start >= span.end:
                    issues.append(
                        DocumentValidationIssue(
                            code="job_span_out_of_bounds",
                            severity="fatal",
                            message=f"source_span ({span.start}, {span.end}) is out of bounds for text of length {len(posting_text)}",
                            claim_id=cid,
                            evidence_reference=ref,
                        )
                    )
                else:
                    span_excerpt = posting_text[span.start:span.end]
                    if not span_excerpt.strip():
                        issues.append(
                            DocumentValidationIssue(
                                code="whitespace_job_span",
                                severity="fatal",
                                message="Span slice in posting text is all-whitespace",
                                claim_id=cid,
                                evidence_reference=ref,
                            )
                        )
                    if quote is not None and quote != span_excerpt:
                        issues.append(
                            DocumentValidationIssue(
                                code="quote_span_mismatch",
                                severity="fatal",
                                message="Quotation and source_span slice disagree",
                                claim_id=cid,
                                evidence_reference=ref,
                            )
                        )
                    expected_excerpt = span_excerpt

            if quote is not None and span is None and posting_text.count(quote) > 1:
                issues.append(
                    DocumentValidationIssue(
                        code="ambiguous_quotation",
                        severity="warning",
                        message="Quotation occurs multiple times in posting text without a specifying span",
                        claim_id=cid,
                        evidence_reference=ref,
                        review_reason="ambiguous_excerpt",
                        suggested_action="Review whether this excerpt corresponds to the intended job requirement",
                    )
                )

            if expected_excerpt is not None and claim.text != expected_excerpt:
                issues.append(
                    DocumentValidationIssue(
                        code="claim_text_mismatch",
                        severity="fatal",
                        message=f"Claim text does not match source excerpt: '{claim.text}' != '{expected_excerpt}'",
                        claim_id=cid,
                        evidence_reference=ref,
                    )
                )

            # Protected source value check
            if pv is not None:
                if pv.source_field != claim.source_field or pv.evidence_reference != ref:
                    issues.append(
                        DocumentValidationIssue(
                            code="protected_value_mismatch",
                            severity="fatal",
                            message="ProtectedSourceValue does not match job claim reference or field",
                            claim_id=cid,
                            evidence_reference=ref,
                        )
                    )
                if pv.original_value != posting_text:
                    issues.append(
                        DocumentValidationIssue(
                            code="protected_original_value_mismatch",
                            severity="fatal",
                            message="ProtectedSourceValue original_value does not match full job field text",
                            claim_id=cid,
                            evidence_reference=ref,
                        )
                    )

            resolved_claims[cid] = {
                "subject": "job",
                "field": ref.field_path,
                "posting_text": posting_text,
                "expected_excerpt": expected_excerpt,
            }
        else:
            issues.append(
                DocumentValidationIssue(
                    code="unknown_claim_subject",
                    severity="fatal",
                    message=f"Unknown claim subject '{claim.claim_subject}'",
                    claim_id=cid,
                )
            )

    source_map = {
        "claims": resolved_claims,
        "facts_by_id": facts_by_id,
        "protected_values": pv_by_claim_id,
    }
    return source_map, issues

