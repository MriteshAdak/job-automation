"""Availability stage coordinator reconciling source manifests and canonical availability (RUN-01-S05)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.sources import SourceConfig
from job_automation.identity.availability.models import AvailabilityProcessResult
from job_automation.identity.availability.service import AvailabilityService
from job_automation.orchestration.checkpoints import CheckpointCoordinator
from job_automation.orchestration.fingerprints import compute_stage_work_fingerprint
from job_automation.orchestration.records import (
    RunAttempt,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.sources.models import EffectiveSource
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


@dataclass
class AvailabilityStageExecutionResult:
    """Outcome of availability stage execution."""

    results: dict[str, AvailabilityProcessResult] = field(default_factory=dict)
    changed_canonical_ids: set[uuid.UUID] = field(default_factory=set)
    total_manifests_processed: int = 0


class AvailabilityStageCoordinator:
    """Coordinates consumption of sealed C04 manifests and canonical availability projections."""

    def __init__(
        self,
        engine: StorageEngine,
        availability_service: AvailabilityService,
    ) -> None:
        self.engine = engine
        self.availability_service = availability_service
        self.checkpoint_coord = CheckpointCoordinator(engine)

    def execute_availability(
        self,
        request: RunRequest,
        attempt: RunAttempt,
        manifests: Mapping[str, FetchManifest],
        effective_sources: Mapping[str, EffectiveSource] | None = None,
    ) -> AvailabilityStageExecutionResult:
        """Process sealed C04 manifests for availability reconciliation."""
        run_id = request.run_id
        self.checkpoint_coord.record_stage_start(run_id, "availability")

        results: dict[str, AvailabilityProcessResult] = {}
        changed_canonical_ids: set[uuid.UUID] = set()

        for src_key, manifest in manifests.items():
            eff_source = effective_sources.get(src_key) if effective_sources else None
            source_cfg = eff_source.config if eff_source else None

            work_key = f"avail:{manifest.scope_id}"
            fp = compute_stage_work_fingerprint(
                stage_name="availability",
                work_key=work_key,
                inputs={"manifest_outcome": manifest.outcome.value, "page_count": manifest.page_count},
            )

            res = self.availability_service.process_manifest(
                manifest=manifest,
                source_config=source_cfg,
            )
            results[src_key] = res

            for chg in res.canonical_changes:
                changed_canonical_ids.add(chg.canonical_job_id)

            work = StageWorkRecord(
                run_id=run_id,
                attempt_id=attempt.attempt_id,
                stage_name="availability",
                work_key=work_key,
                input_fingerprint=fp,
                output_id=manifest.scope_id,
                state=WorkItemState.COMPLETED,
                checkpoint_data={
                    "positive_observations_count": res.positive_observations_count,
                    "miss_evaluations_count": res.miss_evaluations_count,
                    "canonical_changes": len(res.canonical_changes),
                },
            )
            self.engine.pipeline_work.save_stage_work(work)

        self.checkpoint_coord.record_stage_complete(
            run_id=run_id,
            stage_name="availability",
            checkpoint_data={
                "manifests_processed": len(manifests),
                "changed_canonical_jobs": len(changed_canonical_ids),
            },
        )

        return AvailabilityStageExecutionResult(
            results=results,
            changed_canonical_ids=changed_canonical_ids,
            total_manifests_processed=len(manifests),
        )
