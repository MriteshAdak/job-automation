"""Run ledger, stage lifecycle, and checkpoint repository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.enums import PipelineStage, RunStatus
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.runs import RunSummary
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class RunLedgerRepository(BaseRepository):
    """Manages pipeline run summaries, stage lifecycle transitions, and checkpoints."""

    def create_run(
        self,
        run_id: uuid.UUID,
        start_time: UtcDatetime | None = None,
        status: str = "running",
        notes: str | None = None,
    ) -> None:
        """Initialize a new pipeline run entry in the ledger."""
        now_utc = (start_time or datetime.now(timezone.utc)).isoformat()
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, start_time, end_time, status,
                        source_counts_json, metrics_json, summary_json,
                        created_at, updated_at, notes
                    ) VALUES (?, ?, NULL, ?, '{}', '{}', NULL, ?, ?, ?)
                    """,
                    (str(run_id), now_utc, status, now_utc, now_utc, notes),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"Run with ID '{run_id}' already exists", constraint="runs_pk"
                ) from exc
            raise

    def record_stage(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        status: PipelineStage,
        started_at: UtcDatetime | None = None,
        completed_at: UtcDatetime | None = None,
        error: ClassifiedError | None = None,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> None:
        """Record or update lifecycle status of a pipeline stage."""
        stage_id = f"{run_id}_{stage_name}"
        start_str = (started_at or datetime.now(timezone.utc)).isoformat()
        comp_str = completed_at.isoformat() if completed_at else None
        err_json = error.model_dump_json() if error else None
        chk_json = json.dumps(checkpoint_data) if checkpoint_data else None

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_stages (
                    stage_id, run_id, stage_name, status, started_at,
                    completed_at, error_json, checkpoint_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stage_id) DO UPDATE SET
                    status = excluded.status,
                    completed_at = COALESCE(excluded.completed_at, run_stages.completed_at),
                    error_json = COALESCE(excluded.error_json, run_stages.error_json),
                    checkpoint_json = COALESCE(excluded.checkpoint_json, run_stages.checkpoint_json)
                """,
                (
                    stage_id,
                    str(run_id),
                    stage_name,
                    status.value,
                    start_str,
                    comp_str,
                    err_json,
                    chk_json,
                ),
            )

    def save_checkpoint(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        checkpoint_key: str,
        data: dict[str, Any],
    ) -> None:
        """Save granular stage checkpoint data for resume capability."""
        checkpoint_id = f"{run_id}_{stage_name}_{checkpoint_key}"
        now_utc = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(data)

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO pipeline_checkpoints (
                    checkpoint_id, run_id, stage_name, checkpoint_key,
                    checkpoint_data_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    checkpoint_data_json = excluded.checkpoint_data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    checkpoint_id,
                    str(run_id),
                    stage_name,
                    checkpoint_key,
                    data_json,
                    now_utc,
                    now_utc,
                ),
            )

    def get_checkpoint(
        self,
        run_id: uuid.UUID,
        stage_name: str,
        checkpoint_key: str,
    ) -> dict[str, Any] | None:
        """Retrieve stored checkpoint data if present."""
        checkpoint_id = f"{run_id}_{stage_name}_{checkpoint_key}"
        cursor = self.conn.execute(
            "SELECT checkpoint_data_json FROM pipeline_checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        )
        row = cursor.fetchone()
        if row and row["checkpoint_data_json"]:
            return json.loads(row["checkpoint_data_json"])
        return None

    def complete_run(self, summary: RunSummary) -> None:
        """Finalize an existing run with complete C15 RunSummary."""
        now_utc = datetime.now(timezone.utc).isoformat()
        metrics = {
            "source_postings_count": summary.source_postings_count,
            "canonical_jobs_new": summary.canonical_jobs_new,
            "canonical_jobs_updated": summary.canonical_jobs_updated,
            "canonical_jobs_duplicate": summary.canonical_jobs_duplicate,
            "eligible_count": summary.eligible_count,
            "review_count": summary.review_count,
            "rejected_count": summary.rejected_count,
            "sync_operations_succeeded": summary.sync_operations_succeeded,
            "sync_operations_failed": summary.sync_operations_failed,
        }

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO runs (
                    run_id, start_time, end_time, status,
                    source_counts_json, metrics_json, summary_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    end_time = excluded.end_time,
                    status = excluded.status,
                    source_counts_json = excluded.source_counts_json,
                    metrics_json = excluded.metrics_json,
                    summary_json = excluded.summary_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(summary.run_id),
                    summary.start_time.isoformat(),
                    summary.end_time.isoformat(),
                    summary.status.value,
                    json.dumps(summary.source_counts),
                    json.dumps(metrics),
                    summary.model_dump_json(),
                    now_utc,
                    now_utc,
                ),
            )

    def get_run(self, run_id: uuid.UUID) -> RunSummary | None:
        """Fetch a run summary by UUID."""
        cursor = self.conn.execute(
            "SELECT summary_json, start_time, end_time, status, source_counts_json, metrics_json FROM runs WHERE run_id = ?",
            (str(run_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None

        if row["summary_json"]:
            return RunSummary.model_validate_json(row["summary_json"])

        # In-progress or interrupted run without finalized summary_json
        source_counts = json.loads(row["source_counts_json"]) if row["source_counts_json"] else {}
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        start_dt = datetime.fromisoformat(row["start_time"])
        end_dt = (
            datetime.fromisoformat(row["end_time"])
            if row["end_time"]
            else datetime.now(timezone.utc)
        )
        status = RunStatus.FAILED if row["status"] in ("failed", "running") else RunStatus.PARTIAL

        return RunSummary(
            run_id=run_id,
            start_time=start_dt,
            end_time=end_dt,
            status=status,
            source_counts=source_counts,
            source_postings_count=metrics.get("source_postings_count", 0),
            canonical_jobs_new=metrics.get("canonical_jobs_new", 0),
            canonical_jobs_updated=metrics.get("canonical_jobs_updated", 0),
            canonical_jobs_duplicate=metrics.get("canonical_jobs_duplicate", 0),
            eligible_count=metrics.get("eligible_count", 0),
            review_count=metrics.get("review_count", 0),
            rejected_count=metrics.get("rejected_count", 0),
            sync_operations_succeeded=metrics.get("sync_operations_succeeded", 0),
            sync_operations_failed=metrics.get("sync_operations_failed", 0),
        )

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        """List recent runs in reverse chronological order."""
        cursor = self.conn.execute(
            "SELECT run_id FROM runs ORDER BY start_time DESC LIMIT ?", (limit,)
        )
        results: list[RunSummary] = []
        for row in cursor.fetchall():
            run = self.get_run(uuid.UUID(row["run_id"]))
            if run:
                results.append(run)
        return results

    def get_stages(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        """List all stages recorded for a given run."""
        cursor = self.conn.execute(
            """
            SELECT stage_id, run_id, stage_name, status, started_at, completed_at, error_json, checkpoint_json
            FROM run_stages
            WHERE run_id = ?
            ORDER BY started_at ASC
            """,
            (str(run_id),),
        )
        stages: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            stages.append(
                {
                    "stage_id": row["stage_id"],
                    "run_id": row["run_id"],
                    "stage_name": row["stage_name"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "error": (
                        ClassifiedError.model_validate_json(row["error_json"])
                        if row["error_json"]
                        else None
                    ),
                    "checkpoint_data": (
                        json.loads(row["checkpoint_json"])
                        if row["checkpoint_json"]
                        else None
                    ),
                }
            )
        return stages

    def get_unfinished_runs(self) -> list[dict[str, Any]]:
        """Identify runs that did not complete normally (e.g. status='running' or null end_time)."""
        cursor = self.conn.execute(
            """
            SELECT run_id, start_time, end_time, status, created_at
            FROM runs
            WHERE status = 'running' OR end_time IS NULL
            ORDER BY start_time DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_unfinished_stages(self, run_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        """Identify stages left in running or pending state."""
        if run_id:
            cursor = self.conn.execute(
                """
                SELECT stage_id, run_id, stage_name, status, started_at, checkpoint_json
                FROM run_stages
                WHERE run_id = ? AND status IN ('pending', 'running')
                """,
                (str(run_id),),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT stage_id, run_id, stage_name, status, started_at, checkpoint_json
                FROM run_stages
                WHERE status IN ('pending', 'running')
                """
            )
        return [dict(row) for row in cursor.fetchall()]

    def recover_interrupted_runs(
        self,
        failure_reason: str = "Worker process interrupted unexpectedly",
    ) -> int:
        """Mark uncompleted runs and stages as failed upon process restart/recovery."""
        unfinished = self.get_unfinished_runs()
        if not unfinished:
            return 0

        now_utc = datetime.now(timezone.utc).isoformat()
        classified_err = ClassifiedError.from_category(
            category=ErrorCategory.TRANSIENT_SERVICE,
            message=failure_reason,
            details={"recovery_action": "marked_failed_on_process_restart"},
        )
        err_json = classified_err.model_dump_json()

        count = 0
        with self.conn:
            for item in unfinished:
                rid = item["run_id"]
                self.conn.execute(
                    """
                    UPDATE runs
                    SET status = 'failed', end_time = ?, updated_at = ?
                    WHERE run_id = ? AND (status = 'running' OR end_time IS NULL)
                    """,
                    (now_utc, now_utc, rid),
                )
                self.conn.execute(
                    """
                    UPDATE run_stages
                    SET status = 'failed', completed_at = ?, error_json = ?
                    WHERE run_id = ? AND status IN ('pending', 'running')
                    """,
                    (now_utc, err_json, rid),
                )
                count += 1

        return count
