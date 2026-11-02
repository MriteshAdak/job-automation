"""Stage checkpoints and execution state tracking (RUN-01-S03)."""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.enums import PipelineStage
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime
from job_automation.orchestration.records import StageWorkRecord, WorkItemState
from job_automation.storage.engine import StorageEngine


class CheckpointCoordinator:
    """Manages stage-level progress checkpoints and execution state transitions."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def record_stage_start(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        started_at: UtcDatetime | None = None,
    ) -> None:
        """Mark stage as running in the run ledger."""
        self.engine.runs.record_stage(
            run_id=run_id,
            stage_name=stage_name,
            status=PipelineStage.RUNNING,
            started_at=started_at,
        )

    def record_stage_complete(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        completed_at: UtcDatetime | None = None,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> None:
        """Mark stage as succeeded in the run ledger."""
        self.engine.runs.record_stage(
            run_id=run_id,
            stage_name=stage_name,
            status=PipelineStage.SUCCEEDED,
            completed_at=completed_at,
            checkpoint_data=checkpoint_data,
        )

    def record_stage_failed(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        error: ClassifiedError,
        completed_at: UtcDatetime | None = None,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> None:
        """Mark stage as failed in the run ledger."""
        self.engine.runs.record_stage(
            run_id=run_id,
            stage_name=stage_name,
            status=PipelineStage.FAILED,
            completed_at=completed_at,
            error=error,
            checkpoint_data=checkpoint_data,
        )

    def record_stage_skipped(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        reason: str,
    ) -> None:
        """Mark stage as skipped in the run ledger."""
        self.engine.runs.record_stage(
            run_id=run_id,
            stage_name=stage_name,
            status=PipelineStage.SKIPPED,
            checkpoint_data={"skip_reason": reason},
        )

    def save_work_checkpoint(
        self,
        work: StageWorkRecord,
        data: dict[str, Any],
    ) -> StageWorkRecord:
        """Update granular checkpoint data on a work item."""
        updated = work.model_copy(update={"checkpoint_data": data})
        self.engine.pipeline_work.save_stage_work(updated)
        return updated

    def get_stage_status(self, run_id: uuid.UUID, stage_name: str) -> str | None:
        """Get the current recorded status of a stage for a run."""
        stages = self.engine.runs.get_stages(run_id)
        for s in stages:
            if s["stage_name"] == stage_name:
                return str(s["status"])
        return None

