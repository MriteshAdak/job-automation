"""Repository for RUN-01 pipeline requests, attempts, work receipts, bindings, and selections."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ValidationIssue
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey, UtcDatetime
from job_automation.orchestration.records import (
    AssessmentSelection,
    PostingBinding,
    QuarantineRecord,
    RunAttempt,
    RunReport,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class PipelineWorkRepository(BaseRepository):
    """Storage repository managing durable pipeline work records, attempts, bindings, and selections."""

    # -------------------------------------------------------------------------
    # Run Requests
    # -------------------------------------------------------------------------

    def save_run_request(self, request: RunRequest) -> None:
        """Persist a frozen RunRequest."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_requests (run_id, request_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    request_json = excluded.request_json
                """,
                (
                    str(request.run_id),
                    request.model_dump_json(),
                    request.created_at.isoformat(),
                ),
            )

    def get_run_request(self, run_id: uuid.UUID) -> RunRequest | None:
        """Retrieve a stored RunRequest by run UUID."""
        cursor = self.conn.execute(
            "SELECT request_json FROM run_requests WHERE run_id = ?",
            (str(run_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return RunRequest.model_validate_json(row["request_json"])

    # -------------------------------------------------------------------------
    # Run Attempts
    # -------------------------------------------------------------------------

    def save_run_attempt(self, attempt: RunAttempt) -> None:
        """Record or update a RunAttempt."""
        err_json = attempt.error.model_dump_json() if attempt.error else None
        comp_str = attempt.completed_at.isoformat() if attempt.completed_at else None

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_attempts (
                    attempt_id, run_id, attempt_sequence, status,
                    started_at, completed_at, exit_code, error_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO UPDATE SET
                    status = excluded.status,
                    completed_at = excluded.completed_at,
                    exit_code = excluded.exit_code,
                    error_json = excluded.error_json
                """,
                (
                    str(attempt.attempt_id),
                    str(attempt.run_id),
                    attempt.attempt_sequence,
                    attempt.status,
                    attempt.started_at.isoformat(),
                    comp_str,
                    attempt.exit_code,
                    err_json,
                ),
            )

    def get_latest_attempt(self, run_id: uuid.UUID) -> RunAttempt | None:
        """Retrieve the latest attempt for a given run UUID."""
        cursor = self.conn.execute(
            """
            SELECT attempt_id, run_id, attempt_sequence, status, started_at, completed_at, exit_code, error_json
            FROM run_attempts
            WHERE run_id = ?
            ORDER BY attempt_sequence DESC
            LIMIT 1
            """,
            (str(run_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        err = ClassifiedError.model_validate_json(row["error_json"]) if row["error_json"] else None
        comp = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
        return RunAttempt(
            attempt_id=uuid.UUID(row["attempt_id"]),
            run_id=uuid.UUID(row["run_id"]),
            attempt_sequence=row["attempt_sequence"],
            status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=comp,
            exit_code=row["exit_code"],
            error=err,
        )

    def list_attempts(self, run_id: uuid.UUID) -> list[RunAttempt]:
        """List all attempts for a run in ascending sequence order."""
        cursor = self.conn.execute(
            """
            SELECT attempt_id, run_id, attempt_sequence, status, started_at, completed_at, exit_code, error_json
            FROM run_attempts
            WHERE run_id = ?
            ORDER BY attempt_sequence ASC
            """,
            (str(run_id),),
        )
        attempts: list[RunAttempt] = []
        for row in cursor.fetchall():
            err = ClassifiedError.model_validate_json(row["error_json"]) if row["error_json"] else None
            comp = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            attempts.append(
                RunAttempt(
                    attempt_id=uuid.UUID(row["attempt_id"]),
                    run_id=uuid.UUID(row["run_id"]),
                    attempt_sequence=row["attempt_sequence"],
                    status=row["status"],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    completed_at=comp,
                    exit_code=row["exit_code"],
                    error=err,
                )
            )
        return attempts

    # -------------------------------------------------------------------------
    # Stage Work Records
    # -------------------------------------------------------------------------

    def save_stage_work(self, work: StageWorkRecord) -> None:
        """Insert or update a StageWorkRecord enforcing semantic uniqueness."""
        err_json = work.error.model_dump_json() if work.error else None
        chk_json = json.dumps(work.checkpoint_data) if work.checkpoint_data else None

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO stage_work_records (
                    work_id, run_id, attempt_id, stage_name, work_key,
                    input_fingerprint, output_id, state, checkpoint_json,
                    error_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stage_name, work_key, input_fingerprint) DO UPDATE SET
                    attempt_id = excluded.attempt_id,
                    output_id = COALESCE(excluded.output_id, stage_work_records.output_id),
                    state = excluded.state,
                    checkpoint_json = COALESCE(excluded.checkpoint_json, stage_work_records.checkpoint_json),
                    error_json = excluded.error_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(work.work_id),
                    str(work.run_id),
                    str(work.attempt_id),
                    work.stage_name,
                    work.work_key,
                    work.input_fingerprint,
                    work.output_id,
                    work.state.value,
                    chk_json,
                    err_json,
                    work.created_at.isoformat(),
                    work.updated_at.isoformat(),
                ),
            )

    def get_stage_work(
        self, stage_name: str, work_key: str, input_fingerprint: str
    ) -> StageWorkRecord | None:
        """Look up a StageWorkRecord by its semantic unique key."""
        cursor = self.conn.execute(
            """
            SELECT work_id, run_id, attempt_id, stage_name, work_key,
                   input_fingerprint, output_id, state, checkpoint_json,
                   error_json, created_at, updated_at
            FROM stage_work_records
            WHERE stage_name = ? AND work_key = ? AND input_fingerprint = ?
            """,
            (stage_name, work_key, input_fingerprint),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_stage_work(row)

    def list_stage_work_for_run(
        self, run_id: uuid.UUID, stage_name: str | None = None
    ) -> list[StageWorkRecord]:
        """List work records for a given run and optional stage."""
        if stage_name:
            cursor = self.conn.execute(
                """
                SELECT work_id, run_id, attempt_id, stage_name, work_key,
                       input_fingerprint, output_id, state, checkpoint_json,
                       error_json, created_at, updated_at
                FROM stage_work_records
                WHERE run_id = ? AND stage_name = ?
                ORDER BY created_at ASC
                """,
                (str(run_id), stage_name),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT work_id, run_id, attempt_id, stage_name, work_key,
                       input_fingerprint, output_id, state, checkpoint_json,
                       error_json, created_at, updated_at
                FROM stage_work_records
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (str(run_id),),
            )
        return [self._row_to_stage_work(r) for r in cursor.fetchall()]

    def _row_to_stage_work(self, row: sqlite3.Row) -> StageWorkRecord:
        chk = json.loads(row["checkpoint_json"]) if row["checkpoint_json"] else None
        err = ClassifiedError.model_validate_json(row["error_json"]) if row["error_json"] else None
        return StageWorkRecord(
            work_id=uuid.UUID(row["work_id"]),
            run_id=uuid.UUID(row["run_id"]),
            attempt_id=uuid.UUID(row["attempt_id"]),
            stage_name=row["stage_name"],
            work_key=row["work_key"],
            input_fingerprint=row["input_fingerprint"],
            output_id=row["output_id"],
            state=WorkItemState(row["state"]),
            checkpoint_data=chk,
            error=err,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # -------------------------------------------------------------------------
    # Posting Bindings
    # -------------------------------------------------------------------------

    def save_posting_binding(self, binding: PostingBinding) -> None:
        """Save an immutable posting binding."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO posting_bindings (
                    binding_id, canonical_job_id, revision_id,
                    normalized_content_hash, raw_reference, raw_content_hash,
                    provider, board_id, source_posting_id, c06_json,
                    mapper_version, normalizer_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_job_id, revision_id) DO UPDATE SET
                    normalized_content_hash = excluded.normalized_content_hash,
                    c06_json = excluded.c06_json
                """,
                (
                    str(binding.binding_id),
                    str(binding.canonical_job_id),
                    str(binding.revision_id),
                    binding.normalized_content_hash,
                    binding.raw_reference,
                    binding.raw_content_hash,
                    binding.source_key.provider,
                    binding.source_key.board_id,
                    binding.source_key.source_posting_id,
                    binding.c06_snapshot.model_dump_json(),
                    binding.mapper_version,
                    binding.normalizer_version,
                    binding.created_at.isoformat(),
                ),
            )

    def get_posting_binding(
        self, canonical_job_id: uuid.UUID, revision_id: uuid.UUID
    ) -> PostingBinding | None:
        """Retrieve a posting binding by canonical job and revision ID."""
        cursor = self.conn.execute(
            """
            SELECT binding_id, canonical_job_id, revision_id,
                   normalized_content_hash, raw_reference, raw_content_hash,
                   provider, board_id, source_posting_id, c06_json,
                   mapper_version, normalizer_version, created_at
            FROM posting_bindings
            WHERE canonical_job_id = ? AND revision_id = ?
            """,
            (str(canonical_job_id), str(revision_id)),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_binding(row)

    def get_latest_binding_for_job(self, canonical_job_id: uuid.UUID) -> PostingBinding | None:
        """Retrieve the most recent posting binding for a canonical job."""
        cursor = self.conn.execute(
            """
            SELECT binding_id, canonical_job_id, revision_id,
                   normalized_content_hash, raw_reference, raw_content_hash,
                   provider, board_id, source_posting_id, c06_json,
                   mapper_version, normalizer_version, created_at
            FROM posting_bindings
            WHERE canonical_job_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(canonical_job_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_binding(row)

    def list_posting_bindings_for_job(self, canonical_job_id: uuid.UUID) -> list[PostingBinding]:
        """List all posting bindings for a canonical job."""
        cursor = self.conn.execute(
            """
            SELECT binding_id, canonical_job_id, revision_id,
                   normalized_content_hash, raw_reference, raw_content_hash,
                   provider, board_id, source_posting_id, c06_json,
                   mapper_version, normalizer_version, created_at
            FROM posting_bindings
            WHERE canonical_job_id = ?
            ORDER BY created_at ASC
            """,
            (str(canonical_job_id),),
        )
        return [self._row_to_binding(r) for r in cursor.fetchall()]

    def _row_to_binding(self, row: sqlite3.Row) -> PostingBinding:
        sk = SourceKey(
            provider=row["provider"],
            board_id=row["board_id"],
            source_posting_id=row["source_posting_id"],
        )
        c06 = NormalizedPosting.model_validate_json(row["c06_json"])
        return PostingBinding(
            binding_id=uuid.UUID(row["binding_id"]),
            canonical_job_id=uuid.UUID(row["canonical_job_id"]),
            revision_id=uuid.UUID(row["revision_id"]),
            normalized_content_hash=row["normalized_content_hash"],
            raw_reference=row["raw_reference"],
            raw_content_hash=row["raw_content_hash"],
            source_key=sk,
            c06_snapshot=c06,
            mapper_version=row["mapper_version"],
            normalizer_version=row["normalizer_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -------------------------------------------------------------------------
    # Assessment Selections
    # -------------------------------------------------------------------------

    def save_assessment_selection(self, selection: AssessmentSelection) -> None:
        """Persist an authoritative assessment selection."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO assessment_selections (
                    selection_id, canonical_job_id, candidate_id, purpose,
                    input_fingerprint, assessment_id, evaluated_at,
                    generation_token, is_selected_final, disposition, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_job_id, purpose, generation_token) DO UPDATE SET
                    assessment_id = excluded.assessment_id,
                    input_fingerprint = excluded.input_fingerprint,
                    is_selected_final = excluded.is_selected_final,
                    disposition = excluded.disposition
                """,
                (
                    str(selection.selection_id),
                    str(selection.canonical_job_id),
                    str(selection.candidate_id),
                    selection.purpose,
                    selection.input_fingerprint,
                    str(selection.assessment_id),
                    selection.evaluated_at.isoformat(),
                    selection.generation_token,
                    1 if selection.is_selected_final else 0,
                    selection.disposition.value,
                    selection.created_at.isoformat(),
                ),
            )

    def get_active_selection(
        self, canonical_job_id: uuid.UUID, purpose: str = "assessment"
    ) -> AssessmentSelection | None:
        """Retrieve the authoritative final assessment selection for a job."""
        cursor = self.conn.execute(
            """
            SELECT selection_id, canonical_job_id, candidate_id, purpose,
                   input_fingerprint, assessment_id, evaluated_at,
                   generation_token, is_selected_final, disposition, created_at
            FROM assessment_selections
            WHERE canonical_job_id = ? AND purpose = ? AND is_selected_final = 1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(canonical_job_id), purpose),
        )
        row = cursor.fetchone()
        if not row:
            return None
        from job_automation.contracts.enums import AssessmentDisposition

        return AssessmentSelection(
            selection_id=uuid.UUID(row["selection_id"]),
            canonical_job_id=uuid.UUID(row["canonical_job_id"]),
            candidate_id=uuid.UUID(row["candidate_id"]),
            purpose=row["purpose"],
            input_fingerprint=row["input_fingerprint"],
            assessment_id=uuid.UUID(row["assessment_id"]),
            evaluated_at=datetime.fromisoformat(row["evaluated_at"]),
            generation_token=row["generation_token"],
            is_selected_final=bool(row["is_selected_final"]),
            disposition=AssessmentDisposition(row["disposition"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -------------------------------------------------------------------------
    # Quarantine Records
    # -------------------------------------------------------------------------

    def save_quarantine_record(self, record: QuarantineRecord) -> None:
        """Persist a quarantine record."""
        issues_json = json.dumps([i.model_dump() for i in record.issues])
        draft_json = record.draft.model_dump_json() if record.draft else None

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO quarantine_records (
                    quarantine_id, run_id, provider, board_id,
                    source_posting_id, raw_reference, record_index,
                    issues_json, draft_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.quarantine_id),
                    str(record.run_id),
                    record.source_key.provider,
                    record.source_key.board_id,
                    record.source_key.source_posting_id,
                    record.raw_reference,
                    record.record_index,
                    issues_json,
                    draft_json,
                    record.created_at.isoformat(),
                ),
            )

    def list_quarantine_records(self, run_id: uuid.UUID) -> list[QuarantineRecord]:
        """List all quarantine records for a given run."""
        cursor = self.conn.execute(
            """
            SELECT quarantine_id, run_id, provider, board_id,
                   source_posting_id, raw_reference, record_index,
                   issues_json, draft_json, created_at
            FROM quarantine_records
            WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (str(run_id),),
        )
        records: list[QuarantineRecord] = []
        for row in cursor.fetchall():
            sk = SourceKey(
                provider=row["provider"],
                board_id=row["board_id"],
                source_posting_id=row["source_posting_id"],
            )
            raw_issues = json.loads(row["issues_json"])
            issues = [ValidationIssue.model_validate(i) for i in raw_issues]
            draft = (
                from_json_draft(row["draft_json"])
                if row["draft_json"]
                else None
            )
            records.append(
                QuarantineRecord(
                    quarantine_id=uuid.UUID(row["quarantine_id"]),
                    run_id=uuid.UUID(row["run_id"]),
                    source_key=sk,
                    raw_reference=row["raw_reference"],
                    record_index=row["record_index"],
                    issues=issues,
                    draft=draft,
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return records

    # -------------------------------------------------------------------------
    # Run Reports
    # -------------------------------------------------------------------------

    def save_run_report(self, report: RunReport) -> None:
        """Persist a companion RunReport."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_reports (
                    report_id, run_id, attempt_id, report_version,
                    report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    report_json = excluded.report_json
                """,
                (
                    str(report.report_id),
                    str(report.run_id),
                    str(report.attempt_id),
                    report.report_version,
                    report.model_dump_json(),
                    report.created_at.isoformat(),
                ),
            )

    def get_latest_run_report(self, run_id: uuid.UUID) -> RunReport | None:
        """Retrieve the latest RunReport for a given run UUID."""
        cursor = self.conn.execute(
            """
            SELECT report_json
            FROM run_reports
            WHERE run_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return RunReport.model_validate_json(row["report_json"])


def from_json_draft(json_str: str) -> Any:
    from job_automation.contracts.postings import SourceJobDraft
    return SourceJobDraft.model_validate_json(json_str)
