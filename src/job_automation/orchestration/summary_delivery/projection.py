"""Builder and sanitization for RunSummaryProjection (AUTO-03-S01).

Enforces:
- Truthful, unit-accurate headlines and summaries across all four pipeline outcomes.
- Explicit distinction between 'No postings found' and 'No new jobs'.
- Allowlist sanitization: redaction of tokens, private paths, and secrets.
- Deterministic truncation with explicit truncation markers.
- Immutable first-result snapshot preservation across subsequent revisions.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from job_automation.orchestration.summary_delivery.records import (
    RunCompletionReceipt,
    RunSummaryProjection,
)

# Secret/credential redaction patterns
_SECRET_PATTERNS = [
    re.compile(r"://([^:@]+):([^@]+)@", re.IGNORECASE),  # URLs with user/password
    re.compile(r"(?:api_?key|token|bearer|secret|password|access_token)[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_\-\.]{8,})", re.IGNORECASE),
    re.compile(r"[0-9a-fA-F]{32,64}"),  # Raw secret hashes / auth tokens
]

# Sensitive local absolute paths (Windows drive letters, user profile dirs)
_PATH_PATTERN = re.compile(r"[A-Za-z]:\\[A-Za-z0-9_\.\-\\]+", re.IGNORECASE)


def sanitize_diagnostic_text(text: str | None, max_length: int = 500) -> tuple[str | None, bool]:
    """Sanitize diagnostic text: redact secrets/tokens/paths and deterministically truncate."""
    if not text:
        return None, False

    sanitized = text

    # Redact URLs with credentials
    sanitized = re.sub(r"://([^:@]+):([^@]+)@", "://[REDACTED]@", sanitized)

    # Redact credentials and tokens
    for pat in _SECRET_PATTERNS[1:]:
        sanitized = pat.sub("[REDACTED_CREDENTIAL]", sanitized)

    # Redact full Windows absolute paths to basename or [PATH]
    def _path_replacer(m: re.Match) -> str:
        full_path = m.group(0)
        # Keep just the filename if discernible, else [PATH]
        parts = [p for p in full_path.split("\\") if p]
        if parts:
            return f"...\\{parts[-1]}"
        return "[PATH]"

    sanitized = _PATH_PATTERN.sub(_path_replacer, sanitized)

    # Deterministic truncation
    truncated = False
    marker = "... [TRUNCATED]"
    if len(sanitized) > max_length:
        sanitized = sanitized[: max_length - len(marker)] + marker
        truncated = True

    return sanitized, truncated


def build_sanitized_headline(receipt: RunCompletionReceipt) -> str:
    """Build a concise, truthful headline based on pipeline outcome and observation units."""
    c15 = receipt.c15_summary
    st = c15.status.value.lower()

    if st == "success":
        if c15.source_postings_count == 0:
            return "Search Complete — No postings found"
        elif c15.canonical_jobs_new == 0:
            return f"Search Complete — No new jobs ({c15.source_postings_count} postings observed)"
        else:
            return f"Search Complete — {c15.source_postings_count} postings, {c15.canonical_jobs_new} new jobs"

    elif st == "partial":
        failed_cnt = len(receipt.sources_failed)
        if failed_cnt > 0:
            return f"Search Partial — {failed_cnt} source(s) incomplete or failed"
        elif c15.sync_operations_failed > 0:
            return f"Search Partial — {c15.sync_operations_failed} sync operation(s) failed"
        elif receipt.quarantined_records_count > 0:
            return f"Search Partial — {receipt.quarantined_records_count} records quarantined"
        else:
            return "Search Partial — Incomplete work or pending retries"

    else:  # failed
        err_cat = "Execution Error"
        if c15.errors:
            err_cat = c15.errors[0].category.value.capitalize()
        return f"Search Failed — {err_cat}"


def build_sanitized_summary_text(receipt: RunCompletionReceipt) -> tuple[str, bool]:
    """Build a detailed, truthful summary text for the remote record."""
    c15 = receipt.c15_summary
    st = c15.status.value.lower()
    dur = max(0.0, (receipt.completed_at - receipt.start_time).total_seconds())

    lines: list[str] = []
    lines.append(f"Status: {st.upper()} | Duration: {dur:.1f}s | Attempt #{receipt.attempt_sequence} (Rev {receipt.revision})")

    # Source observations
    if receipt.sources_attempted:
        succ_str = ", ".join(receipt.sources_succeeded) if receipt.sources_succeeded else "none"
        lines.append(f"Sources Succeeded ({len(receipt.sources_succeeded)}/{len(receipt.sources_attempted)}): {succ_str}")
        if receipt.sources_failed:
            fail_str = ", ".join(receipt.sources_failed)
            lines.append(f"Sources Failed: {fail_str}")

    # Units
    lines.append(
        f"Observations: {c15.source_postings_count} raw | "
        f"Jobs: {c15.canonical_jobs_new} new, {c15.canonical_jobs_updated} updated, "
        f"{c15.canonical_jobs_duplicate} duplicates"
    )

    # Dispositions
    lines.append(
        f"Dispositions: {c15.eligible_count} eligible, {c15.review_count} review, "
        f"{c15.rejected_count} rejected | Reused: {receipt.reused_assessments_count}"
    )

    # Sync
    lines.append(
        f"Sync Operations: {c15.sync_operations_succeeded} succeeded, {c15.sync_operations_failed} failed"
    )

    if receipt.quarantined_records_count > 0:
        lines.append(f"Quarantined Records: {receipt.quarantined_records_count}")

    raw_text = "\n".join(lines)
    sanitized, truncated = sanitize_diagnostic_text(raw_text, max_length=1950)
    return sanitized or "", truncated


def build_summary_projection(
    receipt: RunCompletionReceipt,
    org_id: str,
    is_first_completion: bool = True,
    first_result_snapshot_hash: str | None = None,
) -> RunSummaryProjection:
    """Project a committed RunCompletionReceipt into a RunSummaryProjection."""
    c15 = receipt.c15_summary
    duration_seconds = max(0.0, (receipt.completed_at - receipt.start_time).total_seconds())
    completion_key = f"{org_id}:{receipt.run_id}"

    headline = build_sanitized_headline(receipt)
    summary_text, sum_trunc = build_sanitized_summary_text(receipt)

    # Error summary
    err_summary = None
    err_trunc = False
    if c15.errors:
        err_msgs = [f"[{e.category.value}] {e.message}" for e in c15.errors[:3]]
        joined_err = "; ".join(err_msgs)
        err_summary, err_trunc = sanitize_diagnostic_text(joined_err, max_length=500)

    # Pending work summary
    pending_summary = None
    pending_trunc = False
    if c15.pending_work:
        joined_pending = "; ".join(c15.pending_work[:3])
        pending_summary, pending_trunc = sanitize_diagnostic_text(joined_pending, max_length=500)

    any_truncated = sum_trunc or err_trunc or pending_trunc

    # Projection base
    proj = RunSummaryProjection(
        mapping_version="1.0",
        org_id=org_id,
        run_id=receipt.run_id,
        completion_key=completion_key,
        revision=receipt.revision,
        start_time=receipt.start_time,
        end_time=receipt.completed_at,
        duration_seconds=round(duration_seconds, 2),
        pipeline_status=c15.status.value,
        headline=headline,
        summary_text=summary_text,
        source_postings_count=c15.source_postings_count,
        canonical_jobs_new=c15.canonical_jobs_new,
        canonical_jobs_updated=c15.canonical_jobs_updated,
        canonical_jobs_duplicate=c15.canonical_jobs_duplicate,
        eligible_count=c15.eligible_count,
        review_count=c15.review_count,
        rejected_count=c15.rejected_count,
        sync_succeeded=c15.sync_operations_succeeded,
        sync_failed=c15.sync_operations_failed,
        quarantined_count=receipt.quarantined_records_count,
        sources_attempted=list(receipt.sources_attempted),
        sources_succeeded=list(receipt.sources_succeeded),
        sources_failed=list(receipt.sources_failed),
        error_summary=err_summary,
        pending_work_summary=pending_summary,
        first_result_snapshot_hash="",  # Will be set below
        current_revision_hash="",        # Will be set below
        is_first_completion=is_first_completion,
        truncated=any_truncated,
    )

    current_hash = proj.compute_revision_hash()
    initial_hash = first_result_snapshot_hash if (first_result_snapshot_hash and not is_first_completion) else current_hash

    return proj.model_copy(
        update={
            "current_revision_hash": current_hash,
            "first_result_snapshot_hash": initial_hash,
        }
    )
