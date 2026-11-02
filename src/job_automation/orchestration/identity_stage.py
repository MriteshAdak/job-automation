"""Identity stage coordinator resolving canonical entities, revisions, and bindings (RUN-01-S05)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Sequence

from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import NormalizedPosting
from job_automation.identity.service import IdentityService
from job_automation.orchestration.checkpoints import CheckpointCoordinator
from job_automation.orchestration.fingerprints import compute_stage_work_fingerprint
from job_automation.orchestration.posting_bindings import create_and_save_posting_binding
from job_automation.orchestration.records import (
    PostingBinding,
    RunAttempt,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


@dataclass
class IdentityStageExecutionResult:
    """Outcome of identity stage execution."""

    bindings: list[PostingBinding] = field(default_factory=list)
    affected_canonical_ids: set[uuid.UUID] = field(default_factory=set)
    canonical_jobs_new: int = 0
    canonical_jobs_updated: int = 0
    canonical_jobs_duplicate: int = 0
    total_observations_processed: int = 0


class IdentityStageCoordinator:
    """Coordinates canonical job identity resolution, revision snapshots, and bindings."""

    def __init__(
        self,
        engine: StorageEngine,
        identity_service: IdentityService,
    ) -> None:
        self.engine = engine
        self.identity_service = identity_service
        self.checkpoint_coord = CheckpointCoordinator(engine)

    def execute_identity(
        self,
        request: RunRequest,
        attempt: RunAttempt,
        normalized_postings: Sequence[NormalizedPosting],
    ) -> IdentityStageExecutionResult:
        """Resolve identity for normalized postings and commit bindings."""
        run_id = request.run_id
        self.checkpoint_coord.record_stage_start(run_id, "identity")

        bindings: list[PostingBinding] = []
        new_canonical_ids: set[uuid.UUID] = set()
        updated_canonical_ids: set[uuid.UUID] = set()
        duplicate_observations_count = 0
        affected_canonical_ids: set[uuid.UUID] = set()

        for posting in normalized_postings:
            src_key = posting.source_key
            work_key = f"ident:{src_key.provider}:{src_key.board_id}:{src_key.source_posting_id}"
            fp = compute_stage_work_fingerprint(
                stage_name="identity",
                work_key=work_key,
                inputs={"raw_hash": posting.raw_content_hash, "observed_at": posting.observed_at.isoformat()},
            )

            res = self.identity_service.resolve_and_commit(posting)
            binding = create_and_save_posting_binding(self.engine, posting, res)
            bindings.append(binding)
            affected_canonical_ids.add(res.canonical_job_id)

            if res.is_new_canonical:
                new_canonical_ids.add(res.canonical_job_id)
            elif res.is_new_revision:
                updated_canonical_ids.add(res.canonical_job_id)
            else:
                # Same content re-sighting / duplicate observation
                duplicate_observations_count += 1

            work = StageWorkRecord(
                run_id=run_id,
                attempt_id=attempt.attempt_id,
                stage_name="identity",
                work_key=work_key,
                input_fingerprint=fp,
                output_id=str(binding.binding_id),
                state=WorkItemState.COMPLETED,
                checkpoint_data={
                    "canonical_job_id": str(res.canonical_job_id),
                    "revision_id": str(res.revision.revision_id),
                    "is_new_canonical": res.is_new_canonical,
                    "is_new_revision": res.is_new_revision,
                },
            )
            self.engine.pipeline_work.save_stage_work(work)

        # Do not double-count canonical IDs that had multiple revisions in same run
        updated_canonical_ids = updated_canonical_ids - new_canonical_ids

        self.checkpoint_coord.record_stage_complete(
            run_id=run_id,
            stage_name="identity",
            checkpoint_data={
                "canonical_jobs_new": len(new_canonical_ids),
                "canonical_jobs_updated": len(updated_canonical_ids),
                "canonical_jobs_duplicate": duplicate_observations_count,
                "total_observations_processed": len(normalized_postings),
            },
        )

        return IdentityStageExecutionResult(
            bindings=bindings,
            affected_canonical_ids=affected_canonical_ids,
            canonical_jobs_new=len(new_canonical_ids),
            canonical_jobs_updated=len(updated_canonical_ids),
            canonical_jobs_duplicate=duplicate_observations_count,
            total_observations_processed=len(normalized_postings),
        )

