"""Operations repository for cleanup plans, journals, maintenance reports, and backups."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.storage.connection import transaction
from job_automation.storage.repositories.base import BaseRepository


class OperationsRepository(BaseRepository):
    """Manages cleanup plans, transaction-participating journals, maintenance reports, and backups."""

    def save_cleanup_plan(
        self,
        plan_id: uuid.UUID,
        created_at: str,
        expires_at: str,
        store_fingerprint: str,
        policy_fingerprint: str,
        plan_hash: str,
        status: str,
        plan_json: str,
    ) -> None:
        """Persist a reviewable cleanup plan."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO ops_cleanup_plans (
                    plan_id, created_at, expires_at, store_fingerprint,
                    policy_fingerprint, plan_hash, status, plan_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    status = excluded.status,
                    plan_json = excluded.plan_json
                """,
                (
                    str(plan_id),
                    created_at,
                    expires_at,
                    store_fingerprint,
                    policy_fingerprint,
                    plan_hash,
                    status,
                    plan_json,
                ),
            )

    def get_cleanup_plan(self, plan_id: uuid.UUID) -> dict[str, Any] | None:
        """Fetch a cleanup plan by UUID."""
        cursor = self.conn.execute(
            """
            SELECT plan_id, created_at, expires_at, store_fingerprint,
                   policy_fingerprint, plan_hash, status, plan_json
            FROM ops_cleanup_plans
            WHERE plan_id = ?
            """,
            (str(plan_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def update_cleanup_plan_status(self, plan_id: uuid.UUID, status: str) -> None:
        """Update plan execution status."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE ops_cleanup_plans SET status = ? WHERE plan_id = ?",
                (status, str(plan_id)),
            )

    def record_cleanup_journal_step(
        self,
        journal_id: uuid.UUID,
        plan_id: uuid.UUID,
        step_number: int,
        item_path: str,
        stage: str,
        status: str,
        reclaimed_bytes: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a journal entry safely participating in outer transactions."""
        now_utc = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details) if details else None
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO ops_cleanup_journals (
                    journal_id, plan_id, step_number, item_path,
                    stage, status, reclaimed_bytes, details_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(journal_id) DO UPDATE SET
                    stage = excluded.stage,
                    status = excluded.status,
                    reclaimed_bytes = excluded.reclaimed_bytes,
                    details_json = excluded.details_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(journal_id),
                    str(plan_id),
                    step_number,
                    item_path,
                    stage,
                    status,
                    reclaimed_bytes,
                    details_json,
                    now_utc,
                    now_utc,
                ),
            )

    def get_cleanup_journal(self, plan_id: uuid.UUID) -> list[dict[str, Any]]:
        """Return all journal entries for a plan in step order."""
        cursor = self.conn.execute(
            """
            SELECT journal_id, plan_id, step_number, item_path,
                   stage, status, reclaimed_bytes, details_json,
                   created_at, updated_at
            FROM ops_cleanup_journals
            WHERE plan_id = ?
            ORDER BY step_number ASC
            """,
            (str(plan_id),),
        )
        return [dict(r) for r in cursor.fetchall()]

    def get_incomplete_journals(self) -> list[dict[str, Any]]:
        """Return journal entries that were interrupted or not completed."""
        cursor = self.conn.execute(
            """
            SELECT journal_id, plan_id, step_number, item_path,
                   stage, status, reclaimed_bytes, details_json,
                   created_at, updated_at
            FROM ops_cleanup_journals
            WHERE status != 'completed'
            ORDER BY created_at ASC
            """
        )
        return [dict(r) for r in cursor.fetchall()]

    def save_maintenance_report(
        self,
        report_id: uuid.UUID,
        operation_type: str,
        started_at: str,
        completed_at: str,
        status: str,
        integrity_verified: bool,
        restore_tested: bool,
        remote_coverage_status: str,
        report_json: str,
    ) -> None:
        """Persist a maintenance report."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO ops_maintenance_reports (
                    report_id, operation_type, started_at, completed_at,
                    status, integrity_verified, restore_tested,
                    remote_coverage_status, report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    completed_at = excluded.completed_at,
                    status = excluded.status,
                    integrity_verified = excluded.integrity_verified,
                    restore_tested = excluded.restore_tested,
                    remote_coverage_status = excluded.remote_coverage_status,
                    report_json = excluded.report_json
                """,
                (
                    str(report_id),
                    operation_type,
                    started_at,
                    completed_at,
                    status,
                    1 if integrity_verified else 0,
                    1 if restore_tested else 0,
                    remote_coverage_status,
                    report_json,
                    now_utc,
                ),
            )

    def get_maintenance_report(self, report_id: uuid.UUID) -> dict[str, Any] | None:
        """Fetch a maintenance report by UUID."""
        cursor = self.conn.execute(
            """
            SELECT report_id, operation_type, started_at, completed_at,
                   status, integrity_verified, restore_tested,
                   remote_coverage_status, report_json, created_at
            FROM ops_maintenance_reports
            WHERE report_id = ?
            """,
            (str(report_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def list_maintenance_reports(
        self, operation_type: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List maintenance reports chronologically descending."""
        if operation_type:
            cursor = self.conn.execute(
                """
                SELECT report_id, operation_type, started_at, completed_at,
                       status, integrity_verified, restore_tested,
                       remote_coverage_status, report_json, created_at
                FROM ops_maintenance_reports
                WHERE operation_type = ?
                ORDER BY started_at DESC LIMIT ?
                """,
                (operation_type, limit),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT report_id, operation_type, started_at, completed_at,
                       status, integrity_verified, restore_tested,
                       remote_coverage_status, report_json, created_at
                FROM ops_maintenance_reports
                ORDER BY started_at DESC LIMIT ?
                """,
                (limit,),
            )
        return [dict(r) for r in cursor.fetchall()]

    def save_backup_record(
        self,
        backup_id: uuid.UUID,
        created_at: str,
        backup_path: str,
        format_version: str,
        app_version: str,
        schema_version: int,
        completeness_status: str,
        manifest_json: str,
        status: str = "complete",
        is_pinned: bool = False,
        verified_at: str | None = None,
        restore_tested_at: str | None = None,
    ) -> None:
        """Record a backup generation."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO ops_backups (
                    backup_id, created_at, backup_path, format_version,
                    app_version, schema_version, completeness_status,
                    is_pinned, manifest_json, status, verified_at, restore_tested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(backup_id) DO UPDATE SET
                    status = excluded.status,
                    is_pinned = excluded.is_pinned,
                    verified_at = excluded.verified_at,
                    restore_tested_at = excluded.restore_tested_at,
                    manifest_json = excluded.manifest_json
                """,
                (
                    str(backup_id),
                    created_at,
                    backup_path,
                    format_version,
                    app_version,
                    schema_version,
                    completeness_status,
                    1 if is_pinned else 0,
                    manifest_json,
                    status,
                    verified_at,
                    restore_tested_at,
                ),
            )

    def get_backup_record(self, backup_id: uuid.UUID) -> dict[str, Any] | None:
        """Fetch a backup record by UUID."""
        cursor = self.conn.execute(
            """
            SELECT backup_id, created_at, backup_path, format_version,
                   app_version, schema_version, completeness_status,
                   is_pinned, manifest_json, status, verified_at, restore_tested_at
            FROM ops_backups
            WHERE backup_id = ?
            """,
            (str(backup_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def list_backup_records(self, status: str | None = None) -> list[dict[str, Any]]:
        """List recorded backups ordered by creation time descending."""
        if status:
            cursor = self.conn.execute(
                """
                SELECT backup_id, created_at, backup_path, format_version,
                       app_version, schema_version, completeness_status,
                       is_pinned, manifest_json, status, verified_at, restore_tested_at
                FROM ops_backups
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (status,),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT backup_id, created_at, backup_path, format_version,
                       app_version, schema_version, completeness_status,
                       is_pinned, manifest_json, status, verified_at, restore_tested_at
                FROM ops_backups
                ORDER BY created_at DESC
                """
            )
        return [dict(r) for r in cursor.fetchall()]

    def update_backup_status(
        self,
        backup_id: uuid.UUID,
        status: str,
        verified_at: str | None = None,
        restore_tested_at: str | None = None,
    ) -> None:
        """Update backup status and verification timestamps."""
        with transaction(self.conn):
            if verified_at and restore_tested_at:
                self.conn.execute(
                    """
                    UPDATE ops_backups
                    SET status = ?, verified_at = ?, restore_tested_at = ?
                    WHERE backup_id = ?
                    """,
                    (status, verified_at, restore_tested_at, str(backup_id)),
                )
            elif verified_at:
                self.conn.execute(
                    "UPDATE ops_backups SET status = ?, verified_at = ? WHERE backup_id = ?",
                    (status, verified_at, str(backup_id)),
                )
            elif restore_tested_at:
                self.conn.execute(
                    "UPDATE ops_backups SET status = ?, restore_tested_at = ? WHERE backup_id = ?",
                    (status, restore_tested_at, str(backup_id)),
                )
            else:
                self.conn.execute(
                    "UPDATE ops_backups SET status = ? WHERE backup_id = ?",
                    (status, str(backup_id)),
                )

