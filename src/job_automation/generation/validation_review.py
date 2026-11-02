"""Aggregation of review warnings, semantic limitations, and report assembly (GEN-04-S05)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.generation.validation_records import (
    DocumentValidationIssue,
    DocumentValidationReport,
    RuleOutcome,
    SEMANTIC_LIMITS_NOTICE,
    ValidationInputBinding,
    compute_report_hash,
    compute_sha256_digest,
)

STANDARD_RULES = [
    "input_binding_verification",
    "candidate_reference_resolution",
    "job_reference_resolution",
    "date_precision_and_calendar",
    "title_and_identity_equality",
    "verified_metrics_extraction",
    "required_sections_and_structure",
    "catalog_headings_and_subjective",
    "entry_and_entity_consistency",
    "review_warnings_preservation",
    "semantic_limits_disclosure",
]


def assemble_validation_report(
    request_id: uuid.UUID,
    draft: DraftDocumentV2,
    binding: ValidationInputBinding,
    collected_issues: list[DocumentValidationIssue],
    rule_set_id: str = "gen04-extractive-v1",
    validator_version: str = "1.0.0",
    report_id: uuid.UUID | None = None,
) -> DocumentValidationReport:
    """Merge upstream review issues, compute deterministic outcomes, and assemble report."""
    issues: list[DocumentValidationIssue] = list(collected_issues)

    # 1. Inherit upstream review issues from DraftDocumentV2
    for rev in draft.review_issues:
        issues.append(
            DocumentValidationIssue(
                code=rev.code,
                severity="warning",
                message=rev.message,
                inherited_from="draft_review_issues",
                review_reason=rev.uncertainty_kind,
                suggested_action="Review during human verification",
                requires_human_review=True,
            )
        )

    # 2. Deterministic deduplication of issues
    deduped: list[DocumentValidationIssue] = []
    seen = set()
    for issue in issues:
        key = (
            issue.code,
            issue.severity,
            issue.message,
            issue.claim_id,
            issue.entry_id,
            issue.section_id,
            issue.block_id,
            issue.inherited_from,
        )
        if key not in seen:
            seen.add(key)
            deduped.append(issue)

    # Sort issues deterministically: fatal first, then by code, then by claim_id
    deduped.sort(key=lambda i: (0 if i.severity == "fatal" else 1, i.code, i.claim_id or ""))

    fatal_count = sum(1 for i in deduped if i.severity == "fatal")
    warning_count = sum(1 for i in deduped if i.severity == "warning")

    evaluation_status = "complete"
    render_decision = "allowed_for_review" if fatal_count == 0 else "blocked"

    # Assemble rule outcomes
    rule_outcomes: dict[str, RuleOutcome] = {}
    for rule in STANDARD_RULES:
        rule_outcomes[rule] = RuleOutcome(
            rule_id=rule,
            status="checked",
            reason="Rule evaluated deterministically",
        )

    now_utc = datetime.now(timezone.utc)
    rep_id = report_id or uuid.uuid4()

    report_data: dict[str, Any] = {
        "schema_version": "1.0",
        "report_id": rep_id,
        "request_id": request_id,
        "draft_id": draft.draft_id,
        "validated_draft_hash": binding.draft_hash,
        "input_binding": binding,
        "validator_version": validator_version,
        "rule_set_id": rule_set_id,
        "rule_outcomes": rule_outcomes,
        "issues": deduped,
        "fatal_count": fatal_count,
        "warning_count": warning_count,
        "evaluation_status": evaluation_status,
        "render_decision": render_decision,
        "requires_human_review": True,
        "semantic_limits_notice": SEMANTIC_LIMITS_NOTICE,
        "completed_at": now_utc,
        "report_hash": "",
    }

    temp_report = DocumentValidationReport.model_validate(report_data)
    json_clean = json.loads(temp_report.model_dump_json())
    del json_clean["report_hash"]
    report_hash = compute_sha256_digest(json_clean)

    report_data["report_hash"] = report_hash
    return DocumentValidationReport.model_validate(report_data)
