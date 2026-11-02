"""Verified metrics extraction, transplantation detection, and quantitative scanning (GEN-04-S03)."""
from __future__ import annotations

import re
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.generation.validation_records import DocumentValidationIssue

QUANTITATIVE_PATTERN = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*%)|"
    r"(?:\b\d+(?:\.\d+)?\s*(?:percent|prozent|percentage points|prozentpunkte)\b)|"
    r"(?:[\$€£]\s*\d+(?:[,\.]\d+)?(?:\s*[kKmMbB])?\b)|"
    r"(?:\b\d+(?:[,\.]\d+)?\s*(?:USD|EUR|k|Mio|Mrd)\b)",
    re.IGNORECASE,
)


def validate_metrics(
    draft: DraftDocumentV2,
    source_map: dict[str, Any],
) -> list[DocumentValidationIssue]:
    """Validate candidate and job metrics, check for transplantation and ungrounded figures."""
    issues: list[DocumentValidationIssue] = []
    resolved_claims = source_map.get("claims", {})
    facts_by_id = source_map.get("facts_by_id", {})

    # Map claim_id to entry_id and entry's root role fact_id
    claim_to_entry_entity: dict[str, Any] = {}
    for s in draft.sections:
        for entry in s.entries:
            # Determine the primary role fact for this entry
            entry_facts = []
            for cid in entry.claim_ids:
                rc = resolved_claims.get(cid)
                if rc and rc.get("subject") == "candidate":
                    f = rc.get("fact")
                    if f:
                        # Follow parent if child fact
                        p_id = getattr(f, "parent_fact_id", None)
                        root_fact = facts_by_id.get(p_id) if p_id else f
                        entry_facts.append(root_fact.fact_id if root_fact else f.fact_id)
            primary_entity_id = entry_facts[0] if entry_facts else None
            for cid in entry.claim_ids:
                claim_to_entry_entity[cid] = (entry.entry_id, primary_entity_id)

    for claim in draft.claims:
        cid = claim.claim_id
        resolved = resolved_claims.get(cid)
        if not resolved:
            continue

        # 1. Candidate Metric Claims
        if claim.claim_subject == "candidate" and claim.source_field == "metrics":
            fact = resolved.get("fact")
            if not fact:
                continue

            metrics_list = getattr(fact, "metrics", [])
            if not isinstance(metrics_list, list) or claim.source_index is None or claim.source_index >= len(metrics_list):
                issues.append(
                    DocumentValidationIssue(
                        code="metric_index_invalid",
                        severity="fatal",
                        message=f"Candidate metric index {claim.source_index} invalid for fact '{fact.fact_id}'",
                        claim_id=cid,
                        source_field="metrics",
                        evidence_reference=claim.evidence_reference,
                    )
                )
                continue

            approved_metric_str = metrics_list[claim.source_index]
            if claim.text != approved_metric_str:
                issues.append(
                    DocumentValidationIssue(
                        code="metric_value_altered",
                        severity="fatal",
                        message=f"Candidate metric text '{claim.text}' differs from approved source metric '{approved_metric_str}'",
                        claim_id=cid,
                        source_field="metrics",
                        evidence_reference=claim.evidence_reference,
                        suggested_action="Preserve exact source metric string, qualifiers, unit, and scope",
                    )
                )

            # Check transplantation
            if cid in claim_to_entry_entity:
                entry_id, entry_root_id = claim_to_entry_entity[cid]
                # Compare fact's root entity with entry's root entity
                fact_parent = getattr(fact, "parent_fact_id", None)
                fact_root_id = fact_parent if fact_parent else fact.fact_id
                if entry_root_id is not None and fact_root_id != entry_root_id:
                    issues.append(
                        DocumentValidationIssue(
                            code="metric_transplanted",
                            severity="fatal",
                            message=f"Metric from fact '{fact.fact_id}' transplanted into entry '{entry_id}' belonging to fact '{entry_root_id}'",
                            claim_id=cid,
                            entry_id=entry_id,
                            source_field="metrics",
                            evidence_reference=claim.evidence_reference,
                            suggested_action="Ensure metrics remain attached to their originating employment role",
                        )
                    )

        # 2. Scanning for ungrounded quantitative assertions in non-metric claims
        elif claim.claim_subject == "candidate" and claim.source_field != "metrics":
            # If the claim text has a quantitative pattern (e.g. 20%, $50k) that was not in the source field
            matches = QUANTITATIVE_PATTERN.findall(claim.text)
            if matches:
                selected_val = resolved.get("selected_val", "")
                if isinstance(selected_val, str):
                    for match in matches:
                        if match.lower() not in selected_val.lower():
                            issues.append(
                                DocumentValidationIssue(
                                    code="metric_binding_missing",
                                    severity="fatal",
                                    message=f"Quantitative metric '{match}' present in claim text without authorized metric source binding",
                                    claim_id=cid,
                                    source_field=claim.source_field,
                                    evidence_reference=claim.evidence_reference,
                                    suggested_action="Quantitative achievements must cite approved metrics via source_field='metrics'",
                                )
                            )

    # Scan subjective blocks for ungrounded quantitative assertions
    for block in draft.subjective_blocks:
        matches = QUANTITATIVE_PATTERN.findall(block.text)
        if matches:
            issues.append(
                DocumentValidationIssue(
                    code="metric_binding_missing",
                    severity="fatal",
                    message=f"Quantitative figure '{matches[0]}' disguised within subjective block '{block.block_id}'",
                    block_id=block.block_id,
                    suggested_action="Subjective text cannot assert quantitative achievements",
                )
            )

    return issues

