"""Error classifications and pending result helpers for MATCH-02."""

from __future__ import annotations

from typing import Any

from job_automation.assessment.errors import AssessmentError
from job_automation.assessment.llm_records import AssessmentRunResult
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue


class LLMAssessmentError(AssessmentError):
    """Base exception for model-assisted assessment failures."""


def make_pending_result(
    failed_stage: str,
    error: ClassifiedError,
    input_fingerprint: str,
    deterministic_baseline: Assessment,
    validation_issues: list[ValidationIssue] | None = None,
    retryable: bool | None = None,
    audit_references: dict[str, Any] | None = None,
) -> AssessmentRunResult:
    """Create a safe pending AssessmentRunResult preserving baseline and input identity."""
    is_retryable = (
        retryable
        if retryable is not None
        else getattr(error, "recoverable", getattr(error, "retryable", False))
    )

    return AssessmentRunResult(
        status="pending",
        assessment=None,
        input_fingerprint=input_fingerprint,
        failed_stage=failed_stage,
        error=error,
        validation_issues=validation_issues or [],
        retryable=is_retryable,
        deterministic_baseline=deterministic_baseline,
        audit_references=audit_references or {},
    )
