"""Tests for honest C15 RunSummary counts and units (RUN-01-S08)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.orchestration.summary import build_run_summary


class TestSummaries:
    def test_c15_counting_units_are_isolated_and_strictly_defined(self) -> None:
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # 3 source postings observed (2 on arbeitnow, 1 on manual)
        source_counts = {
            "arbeitnow:berlin": 2,
            "manual:csv": 1,
        }

        summary = build_run_summary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            source_counts=source_counts,
            canonical_jobs_new=1,
            canonical_jobs_updated=1,
            canonical_jobs_duplicate=1,
            eligible_count=1,
            review_count=1,
            rejected_count=0,
            sync_operations_succeeded=2,
            sync_operations_failed=0,
        )

        assert summary.source_postings_count == 3
        assert summary.source_counts["arbeitnow:berlin"] == 2
        assert summary.source_counts["manual:csv"] == 1
        assert summary.canonical_jobs_new == 1
        assert summary.canonical_jobs_updated == 1
        assert summary.canonical_jobs_duplicate == 1
        assert summary.eligible_count == 1
        assert summary.review_count == 1
        assert summary.rejected_count == 0
        assert summary.sync_operations_succeeded == 2
        assert summary.sync_operations_failed == 0
        assert summary.status == RunStatus.SUCCESS

    def test_c15_status_determination(self) -> None:
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # 1. Successful run without errors or pending items
        s1 = build_run_summary(run_id=run_id, start_time=now)
        assert s1.status == RunStatus.SUCCESS

        # 2. Fatal preflight failure
        s2 = build_run_summary(
            run_id=run_id,
            start_time=now,
            is_fatal_failure=True,
            errors=[ClassifiedError(category=ErrorCategory.MISSING_CONFIGURATION, message="Fatal", recoverable=False)],
        )
        assert s2.status == RunStatus.FAILED

        # 3. Partial source failure or item error
        s3 = build_run_summary(
            run_id=run_id,
            start_time=now,
            is_partial=True,
            errors=[ClassifiedError(category=ErrorCategory.TRANSIENT_NETWORK, message="Source timeout", recoverable=True)],
        )
        assert s3.status == RunStatus.PARTIAL

        # 4. Pending work items remaining
        s4 = build_run_summary(
            run_id=run_id,
            start_time=now,
            pending_work=["1 pending sync operation"],
        )
        assert s4.status == RunStatus.PARTIAL
