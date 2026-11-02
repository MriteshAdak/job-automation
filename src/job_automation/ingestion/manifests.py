"""C04 FetchManifest generation and idempotent finalization (INGEST-01-S07).

Constructs authoritative C04 FetchManifest contracts according to honest
completeness rules, preserving exact identities and count units.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from job_automation.contracts.adapter_results import Continuation
from job_automation.contracts.enums import FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import UtcDatetime
from job_automation.ingestion.models import PageReceipt
from job_automation.sources.models import EffectiveSource
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


def build_fetch_manifest(
    run_id: uuid.UUID,
    effective_source: EffectiveSource,
    start_time: UtcDatetime,
    end_time: UtcDatetime,
    cursor_in: Continuation | None,
    cursor_out: Continuation | None,
    receipts: Sequence[PageReceipt],
    prior_observed_identities: Sequence[str] | None = None,
    prior_raw_refs: Sequence[str] | None = None,
    prior_page_count: int = 0,
    stopped_by_limit: bool = False,
    stopped_by_error: ClassifiedError | None = None,
    used_cache: bool = False,
    is_resumed_without_prefix: bool = False,
) -> FetchManifest:
    """Build authoritative C04 FetchManifest from committed page receipts and execution state."""
    config = effective_source.config
    source_key = config.source_key
    scope_id = f"{config.provider}_{config.board_id}"

    # Collect distinct parent response refs in first-seen order
    raw_response_refs: list[str] = []
    seen_refs: set[str] = set()
    if prior_raw_refs:
        for ref in prior_raw_refs:
            if ref not in seen_refs:
                seen_refs.add(ref)
                raw_response_refs.append(ref)
    for r in receipts:
        for ref in r.raw_response_refs:
            if ref not in seen_refs:
                seen_refs.add(ref)
                raw_response_refs.append(ref)

    # Collect distinct exact posting IDs in first-observation order
    observed_posting_identities: list[str] = []
    seen_ids: set[str] = set()
    if prior_observed_identities:
        for pid in prior_observed_identities:
            if pid not in seen_ids:
                seen_ids.add(pid)
                observed_posting_identities.append(pid)
    for r in receipts:
        for pid in r.observed_posting_ids:
            if pid not in seen_ids:
                seen_ids.add(pid)
                observed_posting_identities.append(pid)

    # Page count = total logical page positions consumed across segments
    page_count = prior_page_count + len(receipts)

    # Count blocking record errors across all receipts
    total_blocking_issues = sum(
        1 for r in receipts for issue in r.issues if issue.severity == "error"
    )
    total_valid_drafts = sum(
        1 for r in receipts for d in r.draft_results if d.draft is not None
    )

    # Check terminal page status
    last_receipt = receipts[-1] if receipts else None
    terminal_exhaustion = last_receipt.exhausted if last_receipt else False
    terminal_error = last_receipt.page_error if last_receipt else None
    terminal_truncated = last_receipt.truncated if last_receipt else False

    # Determine outcome
    outcome: FetchOutcome
    final_error: ClassifiedError | None = stopped_by_error or terminal_error

    if not observed_posting_identities and (final_error is not None or not receipts):
        # Failure before any usable progress (a captured 403/error alone is not usable progress)
        outcome = FetchOutcome.FAILED
        if final_error is None:
            final_error = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="Fetch failed before committing usable progress",
                details={"source_key": source_key},
            )
    elif stopped_by_limit or stopped_by_error:
        outcome = FetchOutcome.PARTIAL
    elif used_cache:
        outcome = FetchOutcome.PARTIAL
        if final_error is None:
            final_error = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="Traversal included cached pages; partial completeness under v1 contract",
                details={"reason": "cache_reuse", "source_key": source_key},
            )
    elif is_resumed_without_prefix:
        outcome = FetchOutcome.PARTIAL
    elif terminal_truncated or terminal_error:
        outcome = FetchOutcome.PARTIAL
    elif total_blocking_issues > 0 and total_valid_drafts == 0 and not terminal_exhaustion:
        outcome = FetchOutcome.FAILED
    elif total_blocking_issues > 0:
        outcome = FetchOutcome.PARTIAL
        if final_error is None:
            final_error = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Traversal encountered {total_blocking_issues} blocking record errors",
                details={"reason": "blocking_record_issues", "source_key": source_key},
            )
    elif terminal_exhaustion and cursor_in is None:
        outcome = FetchOutcome.COMPLETE
        cursor_out = None
    elif terminal_exhaustion and cursor_in is not None:
        outcome = FetchOutcome.PARTIAL
    else:
        outcome = FetchOutcome.PARTIAL

    # Serialize cursors
    cursor_in_str = cursor_in.encode() if cursor_in is not None else None
    cursor_out_str = cursor_out.encode() if cursor_out is not None else None

    return FetchManifest(
        run_id=run_id,
        source_key=source_key,
        scope_id=scope_id,
        start_time=start_time,
        end_time=end_time,
        cursor_in=cursor_in_str,
        cursor_out=cursor_out_str,
        page_count=page_count,
        raw_response_refs=raw_response_refs,
        observed_posting_identities=observed_posting_identities,
        outcome=outcome,
        inventory_semantics=config.inventory_semantics,
        error=final_error,
    )


def finalize_manifest(storage: StorageEngine, manifest: FetchManifest) -> FetchManifest:
    """Persist manifest to storage idempotently.

    Updates the manifest for (run_id, source_key, scope_id) if it already exists,
    otherwise inserts a new record.
    """
    with storage.conn:
        cur = storage.conn.execute(
            "SELECT manifest_id FROM fetch_manifests WHERE run_id = ? AND source_key = ? AND scope_id = ?",
            (str(manifest.run_id), manifest.source_key, manifest.scope_id),
        )
        row = cur.fetchone()
        if row:
            manifest_id = row["manifest_id"]
            storage.conn.execute(
                """
                UPDATE fetch_manifests
                SET end_time = ?, outcome = ?, manifest_json = ?
                WHERE manifest_id = ?
                """,
                (
                    manifest.end_time.isoformat(),
                    manifest.outcome.value,
                    manifest.model_dump_json(),
                    manifest_id,
                ),
            )
        else:
            storage.conn.execute(
                """
                INSERT INTO fetch_manifests (
                    manifest_id, run_id, source_key, scope_id,
                    start_time, end_time, outcome, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    str(manifest.run_id),
                    manifest.source_key,
                    manifest.scope_id,
                    manifest.start_time.isoformat(),
                    manifest.end_time.isoformat(),
                    manifest.outcome.value,
                    manifest.model_dump_json(),
                ),
            )
    return manifest
