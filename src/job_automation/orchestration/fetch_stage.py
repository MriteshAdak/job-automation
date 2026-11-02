"""Fetch stage coordinator executing and recording multi-source ingestion (RUN-01-S04)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Sequence

from job_automation.contracts.enums import FetchOutcome, PipelineStage
from job_automation.contracts.postings import FetchManifest, SourceJobDraft
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.models import FetchStageResult, SourceFetchResult
from job_automation.orchestration.checkpoints import CheckpointCoordinator
from job_automation.orchestration.fingerprints import compute_stage_work_fingerprint
from job_automation.orchestration.observation_reader import ObservationReader
from job_automation.orchestration.records import (
    RunAttempt,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


@dataclass
class FetchStageExecutionResult:
    """Outcome of fetch stage execution across requested sources."""

    stage_result: FetchStageResult
    manifests: dict[str, FetchManifest] = field(default_factory=dict)
    drafts: list[tuple[SourceJobDraft, str, int]] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    total_raw_observations: int = 0
    sources_attempted: int = 0
    sources_completed: int = 0
    sources_failed: int = 0
    sources_partial: int = 0


class FetchStageCoordinator:
    """Coordinates execution of the fetch stage with checkpointing and per-source isolation."""

    def __init__(
        self,
        engine: StorageEngine,
        controller: FetchController,
    ) -> None:
        self.engine = engine
        self.controller = controller
        self.reader = ObservationReader(engine)
        self.checkpoint_coord = CheckpointCoordinator(engine)

    def execute_fetch(
        self,
        request: RunRequest,
        attempt: RunAttempt,
    ) -> FetchStageExecutionResult:
        """Execute acquisition across configured or requested sources."""
        run_id = request.run_id
        self.checkpoint_coord.record_stage_start(run_id, "fetch")

        try:
            stage_res = self.controller.run_fetch(
                run_id=run_id,
                source_keys=request.source_keys,
                resume=True,
            )
        except Exception as exc:
            logger.exception("Fetch stage encountered fatal error: %s", exc)
            from job_automation.contracts.errors import ClassifiedError, ErrorCategory
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Fatal preflight or execution error in fetch controller: {exc}",
            )
            self.checkpoint_coord.record_stage_failed(run_id, "fetch", error=err)
            raise

        manifests: dict[str, FetchManifest] = {}
        source_counts: dict[str, int] = {}

        for src_key, src_res in stage_res.source_results.items():
            if src_res.manifest:
                manifests[src_key] = src_res.manifest
            source_counts[src_key] = src_res.raw_records_count

            # Record per-source stage work
            state = (
                WorkItemState.COMPLETED
                if src_res.outcome == FetchOutcome.COMPLETE
                else (
                    WorkItemState.COMPLETED
                    if src_res.outcome == FetchOutcome.PARTIAL
                    else WorkItemState.FAILED
                )
            )
            fp = compute_stage_work_fingerprint(
                stage_name="fetch",
                work_key=f"source:{src_key}",
                inputs={"run_id": str(run_id), "source_key": src_key},
            )
            work_record = StageWorkRecord(
                run_id=run_id,
                attempt_id=attempt.attempt_id,
                stage_name="fetch",
                work_key=f"source:{src_key}",
                input_fingerprint=fp,
                output_id=src_res.manifest.scope_id if src_res.manifest else None,
                state=state,
                checkpoint_data={
                    "page_count": src_res.page_count,
                    "raw_records_count": src_res.raw_records_count,
                    "outcome": src_res.outcome.value,
                },
                error=src_res.error,
            )
            self.engine.pipeline_work.save_stage_work(work_record)

        drafts = self.reader.extract_drafts_from_fetch_result(stage_res)

        self.checkpoint_coord.record_stage_complete(
            run_id=run_id,
            stage_name="fetch",
            checkpoint_data={
                "sources_attempted": stage_res.sources_attempted,
                "sources_completed": stage_res.sources_completed,
                "sources_partial": stage_res.sources_partial,
                "sources_failed": stage_res.sources_failed,
                "total_raw_observations": stage_res.total_raw_observations,
            },
        )

        return FetchStageExecutionResult(
            stage_result=stage_res,
            manifests=manifests,
            drafts=drafts,
            source_counts=source_counts,
            total_raw_observations=stage_res.total_raw_observations,
            sources_attempted=stage_res.sources_attempted,
            sources_completed=stage_res.sources_completed,
            sources_failed=stage_res.sources_failed,
            sources_partial=stage_res.sources_partial,
        )

