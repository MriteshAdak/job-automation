"""Companion RunReport and terminal formatting (RUN-01-S08).

Provides:
- Detailed breakdown supplementing C15 RunSummary.
- Human-readable terminal output and structured JSON export.
- Safe diagnostics without secret leakage.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.runs import RunSummary


class RunReport(ContractModel):
    """Detailed companion run report extending C15 RunSummary."""

    c15_summary: RunSummary = Field(description="Primary C15 RunSummary record")
    attempt_sequence: int = Field(default=1, description="Run attempt sequence number")
    assessment_mode: str = Field(default="rules", description="Assessment mode: rules or llm")
    sources_attempted: list[str] = Field(default_factory=list)
    sources_succeeded: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
    quarantined_records_count: int = 0
    availability_transitions_count: int = 0
    reused_assessments_count: int = 0
    model_invocations_count: int = 0
    candidate_backup_records_read: int = 0
    candidate_backup_snapshots_saved: int = 0
    candidate_backup_complete: bool = True
    stage_statuses: dict[str, str] = Field(default_factory=dict)
    exit_code: int = 0

    def to_json(self, indent: int = 2) -> str:
        """Format companion report as JSON."""
        return self.model_dump_json(indent=indent)

    def to_text(self) -> str:
        """Format clean, human-readable terminal output."""
        s = self.c15_summary
        status_str = s.status.value.upper()
        dur = (s.end_time - s.start_time).total_seconds()

        lines = [
            "==================================================================",
            f"  PIPELINE RUN REPORT — {status_str}",
            "==================================================================",
            f"  Run ID:              {s.run_id}",
            f"  Attempt:             #{self.attempt_sequence}",
            f"  Assessment Mode:     {self.assessment_mode}",
            f"  Duration:            {dur:.2f}s  ({s.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')} -> {s.end_time.strftime('%H:%M:%S UTC')})",
            f"  Exit Code:           {self.exit_code}",
            "------------------------------------------------------------------",
            "  DISCOVERY & ACQUISITION",
            f"    Sources Attempted: {len(self.sources_attempted)} ({', '.join(self.sources_attempted) if self.sources_attempted else 'none'})",
            f"    Sources Succeeded: {len(self.sources_succeeded)}",
            f"    Sources Failed:    {len(self.sources_failed)} ({', '.join(self.sources_failed) if self.sources_failed else 'none'})",
            f"    Source Postings:   {s.source_postings_count} raw observations",
            f"    Quarantined:       {self.quarantined_records_count} invalid records",
            "------------------------------------------------------------------",
            "  IDENTITY & AVAILABILITY",
            f"    New Canonical:     {s.canonical_jobs_new} jobs",
            f"    Updated Canonical: {s.canonical_jobs_updated} jobs",
            f"    Duplicate Postings:{s.canonical_jobs_duplicate} observations",
            f"    Availability Chg:  {self.availability_transitions_count} transitions",
            "------------------------------------------------------------------",
            "  ASSESSMENT (C11)",
            f"    Eligible:          {s.eligible_count}",
            f"    Review:            {s.review_count}",
            f"    Rejected:          {s.rejected_count}",
            f"    Reused / Cached:   {self.reused_assessments_count}",
            f"    Model Calls:       {self.model_invocations_count}",
            "------------------------------------------------------------------",
            "  SALESFORCE SYNC (C12)",
            f"    Operations Succ:   {s.sync_operations_succeeded}",
            f"    Operations Failed: {s.sync_operations_failed}",
            f"    Backup Snapshots:  {self.candidate_backup_snapshots_saved} saved ({'complete' if self.candidate_backup_complete else 'partial/pending'})",
        ]

        if self.stage_statuses:
            lines.append("------------------------------------------------------------------")
            lines.append("  STAGE PROGRESS")
            for stage, st in self.stage_statuses.items():
                lines.append(f"    {stage:<18} [{st.upper()}]")

        if s.pending_work:
            lines.append("------------------------------------------------------------------")
            lines.append("  PENDING WORK")
            for pw in s.pending_work:
                lines.append(f"    - {pw}")

        if s.errors:
            lines.append("------------------------------------------------------------------")
            lines.append("  ERRORS")
            for err in s.errors:
                lines.append(f"    [{err.category.value}] {err.message}")

        lines.append("==================================================================")
        return "\n".join(lines)

