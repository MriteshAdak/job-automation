"""C15 RunSummary builder with honest, strictly defined counting units (RUN-01-S08).

Enforces:
- Source counts strictly represent raw source-record observations accepted into durable page evidence.
- Canonical new/updated/duplicate counts reflect distinct logical events.
- Disposition counts reflect distinct newly evaluated canonical jobs in this logical run.
- Sync counts reflect distinct C12 sync operations, never raw write steps.
- Status reflects success, partial, or failed honestly based on stage completion and pending work.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.runs import RunSummary


def build_run_summary(
    run_id: uuid.UUID,
    start_time: UtcDatetime,
    end_time: UtcDatetime | None = None,
    source_counts: dict[str, int] | None = None,
    canonical_jobs_new: int = 0,
    canonical_jobs_updated: int = 0,
    canonical_jobs_duplicate: int = 0,
    eligible_count: int = 0,
    review_count: int = 0,
    rejected_count: int = 0,
    sync_operations_succeeded: int = 0,
    sync_operations_failed: int = 0,
    errors: Sequence[ClassifiedError] | None = None,
    pending_work: Sequence[str] | None = None,
    is_fatal_failure: bool = False,
    is_partial: bool = False,
) -> RunSummary:
    """Build a compliant C15 RunSummary record.

    Status calculation:
    - FAILED: Fatal preflight, storage failure, or wholly failed required work.
    - PARTIAL: Some usable progress made, but partial source/item/sync failure or pending required work.
    - SUCCESS: All planned work completed successfully without pending items or unrecovered errors.
    """
    final_end = end_time or datetime.now(timezone.utc)
    sc = dict(source_counts or {})
    total_source_postings = sum(sc.values())

    err_list = list(errors or [])
    pending_list = list(pending_work or [])

    if is_fatal_failure:
        status = RunStatus.FAILED
    elif is_partial or len(err_list) > 0 or len(pending_list) > 0 or sync_operations_failed > 0:
        status = RunStatus.PARTIAL
    else:
        status = RunStatus.SUCCESS

    return RunSummary(
        run_id=run_id,
        start_time=start_time,
        end_time=final_end,
        status=status,
        source_counts=sc,
        source_postings_count=total_source_postings,
        canonical_jobs_new=max(0, canonical_jobs_new),
        canonical_jobs_updated=max(0, canonical_jobs_updated),
        canonical_jobs_duplicate=max(0, canonical_jobs_duplicate),
        eligible_count=max(0, eligible_count),
        review_count=max(0, review_count),
        rejected_count=max(0, rejected_count),
        sync_operations_succeeded=max(0, sync_operations_succeeded),
        sync_operations_failed=max(0, sync_operations_failed),
        errors=err_list,
        pending_work=pending_list,
    )

