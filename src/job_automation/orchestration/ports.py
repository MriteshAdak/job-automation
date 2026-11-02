"""Protocols and interfaces for pipeline orchestration and recovery (RUN-01)."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol, Sequence

from job_automation.contracts.primitives import UtcDatetime
from job_automation.orchestration.records import (
    AssessmentMode,
    OwnerKind,
    RunAttempt,
    RunReport,
    RunRequest,
)


class WorkerLockPort(Protocol):
    """Protocol for acquiring exclusive process ownership over a runtime data deployment."""

    def acquire(
        self,
        resource: str,
        owner_kind: OwnerKind = OwnerKind.SEARCH,
        attempt_id: uuid.UUID | None = None,
        timeout_seconds: float = 0.0,
    ) -> ContextManager[Any]:
        """Acquire an exclusive OS-held process lock or raise LockContentionError."""
        ...


class PipelineRunnerPort(Protocol):
    """Protocol for executing or resuming bounded pipeline runs."""

    def run(
        self,
        run_request: RunRequest,
    ) -> RunReport:
        """Execute a full or resumed pipeline run returning final report."""
        ...

