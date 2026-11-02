"""Normalization stage coordinator converting drafts into C06 postings or quarantine (RUN-01-S04)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Sequence

from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.contracts.postings import NormalizedPosting, SourceJobDraft
from job_automation.ingestion.normalization.service import DefaultNormalizer
from job_automation.orchestration.checkpoints import CheckpointCoordinator
from job_automation.orchestration.fingerprints import compute_stage_work_fingerprint
from job_automation.orchestration.records import (
    QuarantineRecord,
    RunAttempt,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


@dataclass
class NormalizeStageExecutionResult:
    """Outcome of normalization stage execution."""

    normalized_postings: list[NormalizedPosting] = field(default_factory=list)
    quarantine_records: list[QuarantineRecord] = field(default_factory=list)
    total_processed: int = 0
    quarantine_count: int = 0
    warnings_count: int = 0


class NormalizeStageCoordinator:
    """Coordinates execution of normalization stage with quarantine persistence and fault isolation."""

    def __init__(
        self,
        engine: StorageEngine,
        normalizer: DefaultNormalizer,
    ) -> None:
        self.engine = engine
        self.normalizer = normalizer
        self.checkpoint_coord = CheckpointCoordinator(engine)

    def execute_normalization(
        self,
        request: RunRequest,
        attempt: RunAttempt,
        drafts: Sequence[tuple[SourceJobDraft, str, int]],
    ) -> NormalizeStageExecutionResult:
        """Normalize drafts into C06 postings or quarantine records."""
        run_id = request.run_id
        self.checkpoint_coord.record_stage_start(run_id, "normalize")

        normalized_postings: list[NormalizedPosting] = []
        quarantine_records: list[QuarantineRecord] = []
        warnings_total = 0

        for draft, raw_ref, rec_idx in drafts:
            src_key = draft.source_key
            work_key = f"draft:{src_key.provider}:{src_key.board_id}:{src_key.source_posting_id}"
            fp = compute_stage_work_fingerprint(
                stage_name="normalize",
                work_key=work_key,
                inputs={"raw_reference": raw_ref, "record_index": rec_idx},
            )

            res = self.normalizer.normalize_with_quarantine(
                draft=draft,
                input_ref=raw_ref,
                record_index=rec_idx,
            )

            warnings_total += sum(1 for i in res.issues if i.severity == "warning")

            if res.posting is not None:
                normalized_postings.append(res.posting)
                work = StageWorkRecord(
                    run_id=run_id,
                    attempt_id=attempt.attempt_id,
                    stage_name="normalize",
                    work_key=work_key,
                    input_fingerprint=fp,
                    output_id=res.posting.raw_content_hash,
                    state=WorkItemState.COMPLETED,
                )
                self.engine.pipeline_work.save_stage_work(work)
            else:
                # Quarantined due to validation errors
                q_rec = QuarantineRecord(
                    run_id=run_id,
                    source_key=src_key,
                    raw_reference=raw_ref,
                    record_index=rec_idx,
                    issues=res.issues,
                    draft=draft,
                )
                self.engine.pipeline_work.save_quarantine_record(q_rec)
                quarantine_records.append(q_rec)

                err_summary = "; ".join(i.message for i in res.issues if i.severity == "error")
                c_err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Posting quarantined: {err_summary}",
                    details={"field_path": res.issues[0].field_path if res.issues else None},
                )
                work = StageWorkRecord(
                    run_id=run_id,
                    attempt_id=attempt.attempt_id,
                    stage_name="normalize",
                    work_key=work_key,
                    input_fingerprint=fp,
                    state=WorkItemState.FAILED,
                    error=c_err,
                )
                self.engine.pipeline_work.save_stage_work(work)

        self.checkpoint_coord.record_stage_complete(
            run_id=run_id,
            stage_name="normalize",
            checkpoint_data={
                "total_processed": len(drafts),
                "normalized_count": len(normalized_postings),
                "quarantine_count": len(quarantine_records),
                "warnings_count": warnings_total,
            },
        )

        return NormalizeStageExecutionResult(
            normalized_postings=normalized_postings,
            quarantine_records=quarantine_records,
            total_processed=len(drafts),
            quarantine_count=len(quarantine_records),
            warnings_count=warnings_total,
        )

