"""Safe reporting and formatting for generation worker runs (GEN-01-S08)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from job_automation.generation.records import GenerationWorkerReport


def format_worker_report(report: GenerationWorkerReport, as_json: bool = False) -> str:
    """Format worker report into safe human-readable text or structured JSON."""
    if as_json:
        return report.model_dump_json(indent=2)

    lines: list[str] = [
        "Generation Worker Report",
        "========================",
        f"Worker Attempt ID:    {report.worker_attempt_id}",
        f"Started:              {report.started_at.isoformat()}",
        f"Completed:            {report.completed_at.isoformat()}",
        f"Exit Code:            {report.exit_code}",
        "",
        "Processing Counts:",
        f"  Scanned Requests:   {report.scanned_requests}",
        f"  Admitted New:       {report.admitted_requests}",
        f"  Reused Existing:    {report.reused_requests}",
        f"  Completed:          {report.completed_requests}",
        f"  Blocked/Pending:    {report.blocked_requests}",
        f"  Failed:             {report.failed_requests}",
    ]

    if report.recovery_actions:
        lines.append("")
        lines.append("Recovery Actions:")
        for act in report.recovery_actions:
            lines.append(f"  - {act}")

    if report.pending_reasons:
        lines.append("")
        lines.append("Pending / Blocked Stages:")
        for req_id, reason in report.pending_reasons.items():
            lines.append(f"  - Request {req_id}: {reason}")

    if report.errors:
        lines.append("")
        lines.append("Errors Encountered:")
        for err in report.errors:
            lines.append(f"  - [{err.category.value}] {err.message}")

    return "\n".join(lines)

