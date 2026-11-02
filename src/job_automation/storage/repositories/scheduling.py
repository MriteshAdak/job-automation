"""Storage repository for AUTO-01 scheduling definitions, occurrences, and launch attempts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.primitives import UtcDatetime
from job_automation.operations.scheduling.records import (
    BootstrapCategory,
    LaunchAttemptRecord,
    OccurrenceOutcome,
    ScheduleDefinition,
    ScheduleKind,
    ScheduleOccurrence,
)
from job_automation.storage.repositories.base import BaseRepository


class SchedulingRepository(BaseRepository):
    """Storage repository managing durable scheduling definitions, occurrences, and launch audit records."""

    # -------------------------------------------------------------------------
    # Schedule Definitions
    # -------------------------------------------------------------------------

    def save_definition(self, definition: ScheduleDefinition) -> None:
        """Persist or update a versioned ScheduleDefinition."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ops_schedule_definitions (
                    deployment_id, schedule_id, version, definition_hash, enabled,
                    work_kind, timezone, target_times_json, cadence_minutes,
                    activation_epoch, max_lateness_hours, max_retries, retry_delay_seconds,
                    app_config_path, data_root, run_config_path, assessment_mode,
                    llm_strategy, command_timeout_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deployment_id, schedule_id, version) DO UPDATE SET
                    definition_hash = excluded.definition_hash,
                    enabled = excluded.enabled,
                    work_kind = excluded.work_kind,
                    timezone = excluded.timezone,
                    target_times_json = excluded.target_times_json,
                    cadence_minutes = excluded.cadence_minutes,
                    activation_epoch = excluded.activation_epoch,
                    max_lateness_hours = excluded.max_lateness_hours,
                    max_retries = excluded.max_retries,
                    retry_delay_seconds = excluded.retry_delay_seconds,
                    app_config_path = excluded.app_config_path,
                    data_root = excluded.data_root,
                    run_config_path = excluded.run_config_path,
                    assessment_mode = excluded.assessment_mode,
                    llm_strategy = excluded.llm_strategy,
                    command_timeout_seconds = excluded.command_timeout_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    definition.deployment_id,
                    definition.schedule_id,
                    definition.version,
                    definition.definition_hash,
                    1 if definition.enabled else 0,
                    definition.work_kind.value,
                    definition.timezone,
                    json.dumps(definition.target_times),
                    definition.cadence_minutes,
                    definition.activation_epoch.isoformat(),
                    definition.max_lateness_hours,
                    definition.max_retries,
                    definition.retry_delay_seconds,
                    definition.app_config_path,
                    definition.data_root,
                    definition.run_config_path,
                    definition.assessment_mode,
                    definition.llm_strategy,
                    definition.command_timeout_seconds,
                    definition.created_at.isoformat(),
                    definition.updated_at.isoformat(),
                ),
            )

    def get_definition(
        self,
        deployment_id: str,
        schedule_id: str,
        version: int | None = None,
    ) -> ScheduleDefinition | None:
        """Retrieve a specific version of a schedule definition or the latest version."""
        if version is not None:
            query = """
                SELECT deployment_id, schedule_id, version, definition_hash, enabled,
                       work_kind, timezone, target_times_json, cadence_minutes,
                       activation_epoch, max_lateness_hours, max_retries, retry_delay_seconds,
                       app_config_path, data_root, run_config_path, assessment_mode,
                       llm_strategy, command_timeout_seconds, created_at, updated_at
                FROM ops_schedule_definitions
                WHERE deployment_id = ? AND schedule_id = ? AND version = ?
            """
            params: tuple[Any, ...] = (deployment_id, schedule_id, version)
        else:
            query = """
                SELECT deployment_id, schedule_id, version, definition_hash, enabled,
                       work_kind, timezone, target_times_json, cadence_minutes,
                       activation_epoch, max_lateness_hours, max_retries, retry_delay_seconds,
                       app_config_path, data_root, run_config_path, assessment_mode,
                       llm_strategy, command_timeout_seconds, created_at, updated_at
                FROM ops_schedule_definitions
                WHERE deployment_id = ? AND schedule_id = ?
                ORDER BY version DESC LIMIT 1
            """
            params = (deployment_id, schedule_id)

        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_definition(row)

    def list_definitions(self, deployment_id: str | None = None) -> list[ScheduleDefinition]:
        """List active/registered definitions, optionally filtered by deployment."""
        if deployment_id:
            query = """
                SELECT deployment_id, schedule_id, version, definition_hash, enabled,
                       work_kind, timezone, target_times_json, cadence_minutes,
                       activation_epoch, max_lateness_hours, max_retries, retry_delay_seconds,
                       app_config_path, data_root, run_config_path, assessment_mode,
                       llm_strategy, command_timeout_seconds, created_at, updated_at
                FROM ops_schedule_definitions
                WHERE deployment_id = ?
                ORDER BY schedule_id, version DESC
            """
            params: tuple[Any, ...] = (deployment_id,)
        else:
            query = """
                SELECT deployment_id, schedule_id, version, definition_hash, enabled,
                       work_kind, timezone, target_times_json, cadence_minutes,
                       activation_epoch, max_lateness_hours, max_retries, retry_delay_seconds,
                       app_config_path, data_root, run_config_path, assessment_mode,
                       llm_strategy, command_timeout_seconds, created_at, updated_at
                FROM ops_schedule_definitions
                ORDER BY deployment_id, schedule_id, version DESC
            """
            params = ()

        cursor = self.conn.execute(query, params)
        return [self._row_to_definition(r) for r in cursor.fetchall()]

    def _row_to_definition(self, row: sqlite3.Row | tuple) -> ScheduleDefinition:
        target_times = json.loads(row[7]) if isinstance(row[7], str) else row[7]
        return ScheduleDefinition(
            deployment_id=row[0],
            schedule_id=row[1],
            version=row[2],
            definition_hash=row[3],
            enabled=bool(row[4]),
            work_kind=ScheduleKind(row[5]),
            timezone=row[6],
            target_times=target_times,
            cadence_minutes=row[8],
            activation_epoch=datetime.fromisoformat(row[9]),
            max_lateness_hours=row[10],
            max_retries=row[11],
            retry_delay_seconds=row[12],
            app_config_path=row[13],
            data_root=row[14],
            run_config_path=row[15],
            assessment_mode=row[16],
            llm_strategy=row[17],
            command_timeout_seconds=row[18],
            created_at=datetime.fromisoformat(row[19]),
            updated_at=datetime.fromisoformat(row[20]),
        )

    # -------------------------------------------------------------------------
    # Schedule Occurrences
    # -------------------------------------------------------------------------

    def save_occurrence(self, occ: ScheduleOccurrence) -> None:
        """Persist or update an occurrence record."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ops_schedule_occurrences (
                    occurrence_id, deployment_id, schedule_id, definition_version,
                    work_kind, intended_slot, intended_utc_instant, local_offset_minutes,
                    fold, outcome, admitted_run_id, admitted_request_id, retry_count,
                    next_eligible_at, terminal_at, details_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(occurrence_id) DO UPDATE SET
                    outcome = excluded.outcome,
                    admitted_run_id = excluded.admitted_run_id,
                    admitted_request_id = excluded.admitted_request_id,
                    retry_count = excluded.retry_count,
                    next_eligible_at = excluded.next_eligible_at,
                    terminal_at = excluded.terminal_at,
                    details_json = excluded.details_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(occ.occurrence_id),
                    occ.deployment_id,
                    occ.schedule_id,
                    occ.definition_version,
                    occ.work_kind.value,
                    occ.intended_slot,
                    occ.intended_utc_instant.isoformat(),
                    occ.local_offset_minutes,
                    occ.fold,
                    occ.outcome.value,
                    str(occ.admitted_run_id) if occ.admitted_run_id else None,
                    str(occ.admitted_request_id) if occ.admitted_request_id else None,
                    occ.retry_count,
                    occ.next_eligible_at.isoformat() if occ.next_eligible_at else None,
                    occ.terminal_at.isoformat() if occ.terminal_at else None,
                    json.dumps(occ.details_json) if occ.details_json else None,
                    occ.created_at.isoformat(),
                    occ.updated_at.isoformat(),
                ),
            )

    def get_occurrence(self, occurrence_id: uuid.UUID) -> ScheduleOccurrence | None:
        """Retrieve an occurrence by UUID."""
        cursor = self.conn.execute(
            """
            SELECT occurrence_id, deployment_id, schedule_id, definition_version,
                   work_kind, intended_slot, intended_utc_instant, local_offset_minutes,
                   fold, outcome, admitted_run_id, admitted_request_id, retry_count,
                   next_eligible_at, terminal_at, details_json, created_at, updated_at
            FROM ops_schedule_occurrences
            WHERE occurrence_id = ?
            """,
            (str(occurrence_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_occurrence(row)

    def find_occurrence_by_slot(
        self,
        deployment_id: str,
        schedule_id: str,
        definition_version: int,
        intended_slot: str,
    ) -> ScheduleOccurrence | None:
        """Find an occurrence by its unique natural key."""
        cursor = self.conn.execute(
            """
            SELECT occurrence_id, deployment_id, schedule_id, definition_version,
                   work_kind, intended_slot, intended_utc_instant, local_offset_minutes,
                   fold, outcome, admitted_run_id, admitted_request_id, retry_count,
                   next_eligible_at, terminal_at, details_json, created_at, updated_at
            FROM ops_schedule_occurrences
            WHERE deployment_id = ? AND schedule_id = ? AND definition_version = ? AND intended_slot = ?
            """,
            (deployment_id, schedule_id, definition_version, intended_slot),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_occurrence(row)

    def list_occurrences(
        self,
        deployment_id: str | None = None,
        schedule_id: str | None = None,
        limit: int = 100,
    ) -> list[ScheduleOccurrence]:
        """List occurrences ordered by creation time descending."""
        clauses = []
        params: list[Any] = []
        if deployment_id:
            clauses.append("deployment_id = ?")
            params.append(deployment_id)
        if schedule_id:
            clauses.append("schedule_id = ?")
            params.append(schedule_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT occurrence_id, deployment_id, schedule_id, definition_version,
                   work_kind, intended_slot, intended_utc_instant, local_offset_minutes,
                   fold, outcome, admitted_run_id, admitted_request_id, retry_count,
                   next_eligible_at, terminal_at, details_json, created_at, updated_at
            FROM ops_schedule_occurrences
            {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)
        cursor = self.conn.execute(query, tuple(params))
        return [self._row_to_occurrence(r) for r in cursor.fetchall()]

    def get_due_or_retryable_occurrences(
        self,
        deployment_id: str,
        as_of_utc: datetime,
    ) -> list[ScheduleOccurrence]:
        """Retrieve occurrences that are pending, in-progress, or retryable as of a timestamp."""
        iso_as_of = as_of_utc.isoformat()
        cursor = self.conn.execute(
            """
            SELECT occurrence_id, deployment_id, schedule_id, definition_version,
                   work_kind, intended_slot, intended_utc_instant, local_offset_minutes,
                   fold, outcome, admitted_run_id, admitted_request_id, retry_count,
                   next_eligible_at, terminal_at, details_json, created_at, updated_at
            FROM ops_schedule_occurrences
            WHERE deployment_id = ?
              AND (
                outcome = 'due'
                OR outcome = 'in_progress'
                OR outcome = 'partial'
                OR (outcome = 'skipped_busy' AND (next_eligible_at IS NULL OR next_eligible_at <= ?))
                OR (outcome = 'failed' AND next_eligible_at IS NOT NULL AND next_eligible_at <= ?)
              )
            ORDER BY intended_utc_instant ASC
            """,
            (deployment_id, iso_as_of, iso_as_of),
        )
        return [self._row_to_occurrence(r) for r in cursor.fetchall()]

    def _row_to_occurrence(self, row: sqlite3.Row | tuple) -> ScheduleOccurrence:
        details = json.loads(row[15]) if row[15] and isinstance(row[15], str) else row[15]
        return ScheduleOccurrence(
            occurrence_id=uuid.UUID(row[0]),
            deployment_id=row[1],
            schedule_id=row[2],
            definition_version=row[3],
            work_kind=ScheduleKind(row[4]),
            intended_slot=row[5],
            intended_utc_instant=datetime.fromisoformat(row[6]),
            local_offset_minutes=row[7],
            fold=row[8],
            outcome=OccurrenceOutcome(row[9]),
            admitted_run_id=uuid.UUID(row[10]) if row[10] else None,
            admitted_request_id=uuid.UUID(row[11]) if row[11] else None,
            retry_count=row[12],
            next_eligible_at=datetime.fromisoformat(row[13]) if row[13] else None,
            terminal_at=datetime.fromisoformat(row[14]) if row[14] else None,
            details_json=details,
            created_at=datetime.fromisoformat(row[16]),
            updated_at=datetime.fromisoformat(row[17]),
        )

    # -------------------------------------------------------------------------
    # Launch Attempts
    # -------------------------------------------------------------------------

    def save_launch_attempt(self, attempt: LaunchAttemptRecord) -> None:
        """Persist a launch attempt audit record."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ops_launch_attempts (
                    launch_id, occurrence_id, deployment_id, schedule_id,
                    work_kind, task_identity, started_at, completed_at,
                    bootstrap_status, readiness_message, child_pid, child_exit_code,
                    outcome, application_run_id, report_summary_json, sanitized_error,
                    stdout_tail, stderr_tail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(launch_id) DO UPDATE SET
                    completed_at = excluded.completed_at,
                    child_pid = excluded.child_pid,
                    child_exit_code = excluded.child_exit_code,
                    outcome = excluded.outcome,
                    application_run_id = excluded.application_run_id,
                    report_summary_json = excluded.report_summary_json,
                    sanitized_error = excluded.sanitized_error,
                    stdout_tail = excluded.stdout_tail,
                    stderr_tail = excluded.stderr_tail
                """,
                (
                    str(attempt.launch_id),
                    str(attempt.occurrence_id) if attempt.occurrence_id else None,
                    attempt.deployment_id,
                    attempt.schedule_id,
                    attempt.work_kind.value,
                    attempt.task_identity,
                    attempt.started_at.isoformat(),
                    attempt.completed_at.isoformat() if attempt.completed_at else None,
                    attempt.bootstrap_status.value,
                    attempt.readiness_message,
                    attempt.child_pid,
                    attempt.child_exit_code,
                    attempt.outcome,
                    str(attempt.application_run_id) if attempt.application_run_id else None,
                    json.dumps(attempt.report_summary_json) if attempt.report_summary_json else None,
                    attempt.sanitized_error,
                    attempt.stdout_tail,
                    attempt.stderr_tail,
                ),
            )

    def get_launch_attempt(self, launch_id: uuid.UUID) -> LaunchAttemptRecord | None:
        """Retrieve a specific launch attempt record."""
        cursor = self.conn.execute(
            """
            SELECT launch_id, occurrence_id, deployment_id, schedule_id,
                   work_kind, task_identity, started_at, completed_at,
                   bootstrap_status, readiness_message, child_pid, child_exit_code,
                   outcome, application_run_id, report_summary_json, sanitized_error,
                   stdout_tail, stderr_tail
            FROM ops_launch_attempts
            WHERE launch_id = ?
            """,
            (str(launch_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_launch(row)

    def get_latest_launch_attempt(
        self,
        deployment_id: str,
        schedule_id: str | None = None,
    ) -> LaunchAttemptRecord | None:
        """Get the most recent launch attempt for a deployment/schedule."""
        if schedule_id:
            query = """
                SELECT launch_id, occurrence_id, deployment_id, schedule_id,
                       work_kind, task_identity, started_at, completed_at,
                       bootstrap_status, readiness_message, child_pid, child_exit_code,
                       outcome, application_run_id, report_summary_json, sanitized_error,
                       stdout_tail, stderr_tail
                FROM ops_launch_attempts
                WHERE deployment_id = ? AND schedule_id = ?
                ORDER BY started_at DESC LIMIT 1
            """
            params: tuple[Any, ...] = (deployment_id, schedule_id)
        else:
            query = """
                SELECT launch_id, occurrence_id, deployment_id, schedule_id,
                       work_kind, task_identity, started_at, completed_at,
                       bootstrap_status, readiness_message, child_pid, child_exit_code,
                       outcome, application_run_id, report_summary_json, sanitized_error,
                       stdout_tail, stderr_tail
                FROM ops_launch_attempts
                WHERE deployment_id = ?
                ORDER BY started_at DESC LIMIT 1
            """
            params = (deployment_id,)

        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_launch(row)

    def list_launch_attempts(
        self,
        deployment_id: str | None = None,
        occurrence_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[LaunchAttemptRecord]:
        """List launch attempts optionally filtered by deployment or occurrence."""
        conditions = []
        params: list[Any] = []
        if deployment_id:
            conditions.append("deployment_id = ?")
            params.append(deployment_id)
        if occurrence_id:
            conditions.append("occurrence_id = ?")
            params.append(str(occurrence_id))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT launch_id, occurrence_id, deployment_id, schedule_id,
                   work_kind, task_identity, started_at, completed_at,
                   bootstrap_status, readiness_message, child_pid, child_exit_code,
                   outcome, application_run_id, report_summary_json, sanitized_error,
                   stdout_tail, stderr_tail
            FROM ops_launch_attempts
            {where_clause}
            ORDER BY started_at DESC LIMIT ?
        """
        params.append(limit)
        cursor = self.conn.execute(query, tuple(params))
        return [self._row_to_launch(r) for r in cursor.fetchall()]

    def _row_to_launch(self, row: sqlite3.Row | tuple) -> LaunchAttemptRecord:
        summary = json.loads(row[14]) if row[14] and isinstance(row[14], str) else row[14]
        return LaunchAttemptRecord(
            launch_id=uuid.UUID(row[0]),
            occurrence_id=uuid.UUID(row[1]) if row[1] else None,
            deployment_id=row[2],
            schedule_id=row[3],
            work_kind=ScheduleKind(row[4]),
            task_identity=row[5],
            started_at=datetime.fromisoformat(row[6]),
            completed_at=datetime.fromisoformat(row[7]) if row[7] else None,
            bootstrap_status=BootstrapCategory(row[8]),
            readiness_message=row[9],
            child_pid=row[10],
            child_exit_code=row[11],
            outcome=row[12],
            application_run_id=uuid.UUID(row[13]) if row[13] else None,
            report_summary_json=summary,
            sanitized_error=row[15],
            stdout_tail=row[16],
            stderr_tail=row[17],
        )
