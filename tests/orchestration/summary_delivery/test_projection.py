"""Projection and sanitization tests for AUTO-03 (T01, T02, T12)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.summary_delivery.projection import (
    build_sanitized_headline,
    build_sanitized_summary_text,
    build_summary_projection,
    sanitize_diagnostic_text,
)
from job_automation.orchestration.summary_delivery.records import RunCompletionReceipt


class TestSummaryProjection:
    def test_t01_nonempty_success_projection(self) -> None:
        """T01: Nonempty successful search produces honest headline, units, and source counts."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        c15 = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.SUCCESS,
            source_counts={"arbeitnow": 25, "greenhouse": 17},
            source_postings_count=42,
            canonical_jobs_new=5,
            canonical_jobs_updated=2,
            canonical_jobs_duplicate=35,
            eligible_count=3,
            review_count=2,
            rejected_count=0,
            sync_operations_succeeded=5,
            sync_operations_failed=0,
        )
        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=c15,
            sources_attempted=["arbeitnow", "greenhouse"],
            sources_succeeded=["arbeitnow", "greenhouse"],
            reused_assessments_count=10,
        )

        proj = build_summary_projection(receipt, org_id="00D000000000001", is_first_completion=True)

        assert proj.pipeline_status == "success"
        assert proj.headline == "Search Complete — 42 postings, 5 new jobs"
        assert proj.source_postings_count == 42
        assert proj.canonical_jobs_new == 5
        assert proj.canonical_jobs_updated == 2
        assert proj.canonical_jobs_duplicate == 35
        assert proj.is_first_completion is True
        assert proj.first_result_snapshot_hash == proj.current_revision_hash
        assert "Observations: 42 raw" in proj.summary_text
        assert "Jobs: 5 new, 2 updated, 35 duplicates" in proj.summary_text

    def test_t01_truly_empty_success_projection(self) -> None:
        """T01: Truly empty success (0 observations) says 'No postings found'."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        c15 = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.SUCCESS,
            source_counts={"arbeitnow": 0},
            source_postings_count=0,
            canonical_jobs_new=0,
            canonical_jobs_updated=0,
            canonical_jobs_duplicate=0,
            eligible_count=0,
            review_count=0,
            rejected_count=0,
            sync_operations_succeeded=0,
            sync_operations_failed=0,
        )
        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=c15,
            sources_attempted=["arbeitnow"],
            sources_succeeded=["arbeitnow"],
        )

        proj = build_summary_projection(receipt, org_id="00D000000000001")
        assert proj.pipeline_status == "success"
        assert proj.headline == "Search Complete — No postings found"
        assert proj.source_postings_count == 0
        assert proj.canonical_jobs_new == 0

    def test_t01_duplicate_only_success_projection(self) -> None:
        """T01: Duplicate-only success (postings seen but 0 new jobs) says 'No new jobs'."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        c15 = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.SUCCESS,
            source_counts={"arbeitnow": 20},
            source_postings_count=20,
            canonical_jobs_new=0,
            canonical_jobs_updated=2,
            canonical_jobs_duplicate=18,
            eligible_count=1,
            review_count=1,
            rejected_count=0,
            sync_operations_succeeded=2,
            sync_operations_failed=0,
        )
        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=c15,
            sources_attempted=["arbeitnow"],
            sources_succeeded=["arbeitnow"],
        )

        proj = build_summary_projection(receipt, org_id="00D000000000001")
        assert proj.pipeline_status == "success"
        assert proj.headline == "Search Complete — No new jobs (20 postings observed)"
        assert proj.source_postings_count == 20
        assert proj.canonical_jobs_new == 0
        assert proj.canonical_jobs_duplicate == 18

    def test_t02_partial_run_projection(self) -> None:
        """T02: Partial run preserves failed sources, quarantines, and actionable details."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        c15 = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.PARTIAL,
            source_counts={"arbeitnow": 15},
            source_postings_count=15,
            canonical_jobs_new=2,
            canonical_jobs_updated=0,
            canonical_jobs_duplicate=13,
            eligible_count=1,
            review_count=0,
            rejected_count=1,
            sync_operations_succeeded=1,
            sync_operations_failed=1,
            errors=[
                ClassifiedError(
                    category=ErrorCategory.TRANSIENT_NETWORK,
                    message="Source 'greenhouse' connection timeout after 3 retries",
                    recoverable=True,
                )
            ],
            pending_work=["Retry greenhouse acquisition"],
        )
        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="partial",
            c15_summary=c15,
            sources_attempted=["arbeitnow", "greenhouse"],
            sources_succeeded=["arbeitnow"],
            sources_failed=["greenhouse"],
            quarantined_records_count=2,
        )

        proj = build_summary_projection(receipt, org_id="00D000000000001")
        assert proj.pipeline_status == "partial"
        assert proj.headline == "Search Partial — 1 source(s) incomplete or failed"
        assert proj.sources_failed == ["greenhouse"]
        assert proj.quarantined_count == 2
        assert "greenhouse" in (proj.error_summary or "")
        assert "Retry greenhouse" in (proj.pending_work_summary or "")

    def test_t02_failed_run_projection(self) -> None:
        """T02: Wholly failed run produces actionable error headline and zero fabricated counts."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        c15 = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.FAILED,
            source_counts={},
            source_postings_count=0,
            canonical_jobs_new=0,
            canonical_jobs_updated=0,
            canonical_jobs_duplicate=0,
            eligible_count=0,
            review_count=0,
            rejected_count=0,
            sync_operations_succeeded=0,
            sync_operations_failed=0,
            errors=[
                ClassifiedError(
                    category=ErrorCategory.MISSING_CONFIGURATION,
                    message="Approved candidate profile not found for environment",
                    recoverable=False,
                )
            ],
        )
        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="failed",
            c15_summary=c15,
            sources_attempted=[],
            sources_succeeded=[],
            sources_failed=[],
        )

        proj = build_summary_projection(receipt, org_id="00D000000000001")
        assert proj.pipeline_status == "failed"
        assert "Search Failed — Missing_configuration" in proj.headline
        assert "Approved candidate profile not found" in (proj.error_summary or "")

    def test_t12_sanitization_and_redaction(self) -> None:
        """T12: Diagnostic text redacts credentials, passwords, and absolute Windows paths."""
        raw_msg = (
            "Database connection failed at C:\\Users\\mrite\\AppData\\Local\\JobAutomation\\database.db. "
            "Connecting to https://admin:SuperSecretPassword123@salesforce.my.salesforce.com with "
            "token=abcd1234efgh5678ijkl9012mnop3456"
        )
        sanitized, truncated = sanitize_diagnostic_text(raw_msg, max_length=200)

        assert "SuperSecretPassword123" not in sanitized
        assert "https://admin:[REDACTED]@" in sanitized or "://[REDACTED]@" in sanitized
        assert "C:\\Users\\mrite\\AppData" not in sanitized
        assert "...\\database.db" in sanitized or "[PATH]" in sanitized

    def test_t12_deterministic_truncation_marker(self) -> None:
        """T12: Long diagnostics append '... [TRUNCATED]' without silent cut."""
        long_text = "Detailed error occurrence " * 30  # ~780 chars
        sanitized, truncated = sanitize_diagnostic_text(long_text, max_length=200)

        assert truncated is True
        assert len(sanitized) <= 200
        assert sanitized.endswith("... [TRUNCATED]")

    def test_first_hash_preservation_across_revisions(self) -> None:
        """Revision 2 preserves the initial first_result_snapshot_hash."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        c15_rev1 = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.PARTIAL,
            source_postings_count=10,
            canonical_jobs_new=1,
        )
        receipt1 = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="partial",
            c15_summary=c15_rev1,
        )
        proj1 = build_summary_projection(receipt1, org_id="00D000000000001", is_first_completion=True)
        initial_hash = proj1.first_result_snapshot_hash

        # Revision 2 (pipeline resumed and succeeded)
        c15_rev2 = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.SUCCESS,
            source_postings_count=20,
            canonical_jobs_new=3,
        )
        receipt2 = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=2,
            revision=2,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=c15_rev2,
        )
        proj2 = build_summary_projection(
            receipt2,
            org_id="00D000000000001",
            is_first_completion=False,
            first_result_snapshot_hash=initial_hash,
        )

        assert proj2.revision == 2
        assert proj2.is_first_completion is False
        assert proj2.first_result_snapshot_hash == initial_hash
        assert proj2.current_revision_hash != initial_hash

