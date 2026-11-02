"""Quarantine handoff construction and routing (INGEST-02).

Constructs structured quarantine envelopes preserving failed draft locators,
issue lists, and raw references without secret leakage.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from job_automation.contracts.adapter_results import RecordIssue
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.postings import SourceJobDraft
from job_automation.ingestion.normalization.models import QuarantineHandoff


def build_quarantine_handoff(
    draft: SourceJobDraft | None,
    issues: Sequence[ValidationIssue | RecordIssue],
    normalizer_version: str = "1.0.0",
    raw_content_hash: str | None = None,
    input_ref: str | None = None,
    record_index: int | None = None,
) -> QuarantineHandoff:
    """Build a QuarantineHandoff envelope from a failed draft and issue sequence."""
    converted_issues: list[ValidationIssue] = []
    for iss in issues:
        if isinstance(iss, ValidationIssue):
            converted_issues.append(iss)
        elif isinstance(iss, RecordIssue):
            converted_issues.append(
                ValidationIssue(
                    field_path=iss.field_path,
                    code=iss.code,
                    message=iss.message,
                    severity="error" if iss.severity == "error" else "warning",
                )
            )

    draft_ref = draft.raw_reference if draft is not None else (input_ref or "unknown_reference")
    source_key = draft.source_key if draft is not None else None
    mapping_version = (
        draft.source_mapped_fields.get("mapping_version") if draft is not None else None
    )
    observed_at = draft.fetch_time if draft is not None else None

    # If raw_content_hash not passed, check if draft metadata has it
    resolved_hash = raw_content_hash
    if resolved_hash is None and draft is not None:
        resolved_hash = draft.original_fields.get("raw_content_hash") or draft.source_mapped_fields.get("raw_content_hash")

    return QuarantineHandoff(
        quarantine_id=uuid.uuid4(),
        draft_reference=draft_ref,
        raw_content_hash=resolved_hash,
        source_key=source_key,
        mapping_version=mapping_version,
        normalizer_version=normalizer_version,
        observed_at=observed_at,
        issues=converted_issues,
        input_ref=input_ref or (draft.raw_reference if draft else None),
        record_index=record_index,
        quarantined_at=datetime.now(timezone.utc),
    )

