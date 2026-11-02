"""Port interfaces and protocol definitions for MATCH-02."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.assessment.llm_records import (
    AssessmentRequest,
    AssessmentRunResult,
    RequirementSet,
)
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
)
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.policy import SearchPolicy


@runtime_checkable
class AssessorV2Port(Protocol):
    """Protocol for model-assisted assessment service."""

    def assess(self, request: AssessmentRequest) -> AssessmentRunResult:
        """Perform full assessment producing an AssessmentRunResult."""
        ...


@runtime_checkable
class RequirementPreparerPort(Protocol):
    """Protocol for source-backed requirement extraction."""

    def prepare(
        self,
        posting: NormalizedPosting,
        posting_revision: str,
        canonical_job_id: uuid.UUID,
        policy: SearchPolicy | None = None,
        max_requirements: int = 20,
    ) -> RequirementSet:
        """Prepare source-backed requirement set from posting."""
        ...

