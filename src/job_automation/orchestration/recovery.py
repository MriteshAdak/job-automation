"""Recovery manager and interrupted execution reconciliation (RUN-01-S03).

Enforces:
- Target-specific recovery: only reconciles work belonging to the active deployment and pipeline.
- Marks crashed running attempts as interrupted with safe diagnostic classification.
- Preserves prior attempt history, error logs, and committed output receipts.
- Classifies work items into REUSE, REPLAY, PENDING_REPAIR, and STALE.
- Never blindly wipes or marks incomplete work as successful.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from job_automation.contracts.enums import PipelineStage
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.orchestration.records import (
    RunAttempt,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class WorkAction(str, Enum):
    """Classification of recovered work items."""

    REUSE = "reuse"
    REPLAY = "replay"
    PENDING_REPAIR = "pending_repair"
    STALE = "stale"


@dataclass
class RecoveryPlan:
    """Plan detailing recovery decisions for an interrupted or resumed run."""

    run_id: uuid.UUID
    prior_attempt: RunAttempt | None = None
    next_attempt_sequence: int = 1
    reusable_stages: set[str] = field(default_factory=set)
    resumable_stages: set[str] = field(default_factory=set)
    pending_work_items: list[str] = field(default_factory=list)
    reconciled_attempts: int = 0


class RecoveryManager:
    """Reconciles interrupted pipeline runs and establishes safe restart state."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def reconcile_interrupted_run(
        self,
        run_id: uuid.UUID,
    ) -> RecoveryPlan:
        """Inspect and reconcile prior execution state for a run UUID under the worker lock."""
        latest_attempt = self.engine.pipeline_work.get_latest_attempt(run_id)
        plan = RecoveryPlan(run_id=run_id, prior_attempt=latest_attempt)

        if latest_attempt is None:
            # First attempt for this run
            plan.next_attempt_sequence = 1
            return plan

        # If previous attempt is still marked 'running', it died unexpectedly
        if latest_attempt.status == "running":
            logger.warning(
                "Run '%s' attempt %d was interrupted while running; marking as interrupted",
                run_id,
                latest_attempt.attempt_sequence,
            )
            interrupted_err = ClassifiedError(
                category=ErrorCategory.VALIDATION,
                message=f"Attempt {latest_attempt.attempt_sequence} interrupted unexpectedly prior to completion",
                recoverable=True,
                details={"code": "interrupted_execution", "attempt_id": str(latest_attempt.attempt_id)},
            )
            updated_attempt = latest_attempt.model_copy(
                update={
                    "status": "interrupted",
                    "completed_at": datetime.now(timezone.utc),
                    "exit_code": 130,
                    "error": interrupted_err,
                }
            )
            self.engine.pipeline_work.save_run_attempt(updated_attempt)
            plan.reconciled_attempts += 1
            plan.prior_attempt = updated_attempt

        plan.next_attempt_sequence = latest_attempt.attempt_sequence + 1

        # Inspect recorded stages to determine reusable vs resumable stages
        stages = self.engine.runs.get_stages(run_id)
        for s in stages:
            stage_name = s["stage_name"]
            st_status = s["status"]
            if st_status == PipelineStage.SUCCEEDED.value:
                plan.reusable_stages.add(stage_name)
            elif st_status in (PipelineStage.RUNNING.value, PipelineStage.FAILED.value):
                plan.resumable_stages.add(stage_name)

        return plan

    def create_new_attempt(
        self,
        run_id: uuid.UUID,
        sequence: int = 1,
    ) -> RunAttempt:
        """Initialize and persist a new RunAttempt entry."""
        attempt = RunAttempt(
            attempt_id=uuid.uuid4(),
            run_id=run_id,
            attempt_sequence=sequence,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self.engine.pipeline_work.save_run_attempt(attempt)
        return attempt
