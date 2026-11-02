"""Result persistence and consumer adaptation helpers for MATCH-02 (MATCH-02-S07)."""

from __future__ import annotations

import json
from typing import Any

from job_automation.assessment.llm_records import AssessmentRunResult


def serialize_run_result(result: AssessmentRunResult) -> dict[str, Any]:
    """Serialize an AssessmentRunResult into a JSON-compatible dictionary."""
    return result.model_dump(mode="json")


def deserialize_run_result(data: dict[str, Any]) -> AssessmentRunResult:
    """Deserialize an AssessmentRunResult from a JSON dictionary."""
    return AssessmentRunResult.model_validate(data)

