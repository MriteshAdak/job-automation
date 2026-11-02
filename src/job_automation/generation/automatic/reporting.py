"""Safe reporting and formatting for AUTO-02 evaluation executions.

Generates human-readable console output and structured JSON without leaking
candidate facts, private prompts, or credentials.
"""

from __future__ import annotations

import json
from typing import Any

from job_automation.generation.automatic.records import (
    AutomaticDraftEvaluationReport,
)


def format_evaluation_report(
    report: AutomaticDraftEvaluationReport,
    as_json: bool = False,
) -> str:
    """Format an AutomaticDraftEvaluationReport for display or logs."""
    if as_json:
        return report.model_dump_json(indent=2)

    lines: list[str] = [
        "============================================================",
        "AUTO-02 Automatic Drafting Policy Evaluation Report",
        "============================================================",
        f"Evaluation Run ID: {report.run_id}",
        f"Policy ID:         {report.policy_id} ({report.policy_version})",
        f"Evaluated At:      {report.evaluated_at.isoformat()}",
        f"Total Evaluated:   {report.total_candidates_evaluated} candidates",
        "",
        "Outcomes (by Canonical Jobs):",
    ]

    for outcome, count in sorted(report.jobs_by_outcome.items()):
        lines.append(f"  - {outcome:20s}: {count:4d} jobs")

    lines.extend([
        "",
        "Outcomes (by Logical Document Requests):",
    ])
    for outcome, count in sorted(report.requests_by_outcome.items()):
        lines.append(f"  - {outcome:20s}: {count:4d} requests")

    lines.extend([
        "",
        f"Newly Admitted Intents: {len(report.admitted_intents)}",
    ])
    for key in report.admitted_intents:
        lines.append(f"  * {key}")

    lines.extend([
        f"Reused Prior Intents:   {len(report.reused_intents)}",
    ])
    for key in report.reused_intents:
        lines.append(f"  * {key}")

    lines.extend([
        f"Held Decisions:         {len(report.held_decisions)}",
        f"Deferred Decisions:     {len(report.deferred_decisions)}",
    ])

    if report.quota_usage:
        lines.extend([
            "",
            "Active Quota Consumption Snapshot:",
        ])
        for k, v in report.quota_usage.items():
            lines.append(f"  {k}: {v}")

    if report.errors:
        lines.extend([
            "",
            "Execution Errors / Warnings:",
        ])
        for err in report.errors:
            lines.append(f"  ! {err}")

    lines.append("============================================================")
    return "\n".join(lines)

