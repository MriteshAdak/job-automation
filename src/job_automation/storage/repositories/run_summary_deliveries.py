"""Repository for AUTO-03 run completion receipts, summary delivery outbox, and attempt history."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.summary_delivery.records import (
    DeliveryAttemptRecord,
    DeliveryState,
    NotificationState,
    RunCompletionReceipt,
    SummaryDelivery,
)
from job_automation.storage.repositories.base import BaseRepository


class RunSummaryDeliveryRepository(BaseRepository):
    """Storage repository managing run completion receipts, summary deliveries, and attempt audits."""

    # -------------------------------------------------------------------------
    # Run Completion Receipts
    # -------------------------------------------------------------------------

    def save_receipt(self, receipt: RunCompletionReceipt) -> None:
        """Persist or update a durable RunCompletionReceipt."""
        meta_dict = {
            "assessment_mode": receipt.assessment_mode,
            "sources_attempted": receipt.sources_attempted,
            "sources_succeeded": receipt.sources_succeeded,
            "sources_failed": receipt.sources_failed,
            "quarantined_records_count": receipt.quarantined_records_count,
            "availability_transitions_count": receipt.availability_transitions_count,
            "reused_assessments_count": receipt.reused_assessments_count,
            "model_invocations_count": receipt.model_invocations_count,
            "exit_code": receipt.exit_code,
        }
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_completion_receipts (
                    receipt_id, run_id, attempt_sequence, revision, start_time,
                    completed_at, status, c15_summary_json, report_metadata_json,
                    receipt_hash, is_final, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, revision) DO UPDATE SET
                    status = excluded.status,
                    c15_summary_json = excluded.c15_summary_json,
                    report_metadata_json = excluded.report_metadata_json,
                    receipt_hash = excluded.receipt_hash,
                    is_final = excluded.is_final
                """,
                (
                    str(receipt.receipt_id),
                    str(receipt.run_id),
                    receipt.attempt_sequence,
                    receipt.revision,
                    receipt.start_time.isoformat(),
                    receipt.completed_at.isoformat(),
                    receipt.status,
                    receipt.c15_summary.model_dump_json(),
                    json.dumps(meta_dict),
                    receipt.receipt_hash,
                    1 if receipt.is_final else 0,
                    receipt.created_at.isoformat(),
                ),
            )

    def _row_to_receipt(self, row: sqlite3.Row) -> RunCompletionReceipt:
        meta = json.loads(row["report_metadata_json"]) if row["report_metadata_json"] else {}
        c15 = RunSummary.model_validate_json(row["c15_summary_json"])
        return RunCompletionReceipt(
            receipt_id=uuid.UUID(row["receipt_id"]),
            run_id=uuid.UUID(row["run_id"]),
            attempt_sequence=row["attempt_sequence"],
            revision=row["revision"],
            start_time=datetime.fromisoformat(row["start_time"]),
            completed_at=datetime.fromisoformat(row["completed_at"]),
            status=row["status"],
            c15_summary=c15,
            assessment_mode=meta.get("assessment_mode", "rules"),
            sources_attempted=meta.get("sources_attempted", []),
            sources_succeeded=meta.get("sources_succeeded", []),
            sources_failed=meta.get("sources_failed", []),
            quarantined_records_count=meta.get("quarantined_records_count", 0),
            availability_transitions_count=meta.get("availability_transitions_count", 0),
            reused_assessments_count=meta.get("reused_assessments_count", 0),
            model_invocations_count=meta.get("model_invocations_count", 0),
            exit_code=meta.get("exit_code", 0),
            receipt_hash=row["receipt_hash"],
            is_final=bool(row["is_final"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_receipt(self, run_id: uuid.UUID, revision: int | None = None) -> RunCompletionReceipt | None:
        """Fetch a specific receipt by run ID and revision, or the highest revision if omitted."""
        if revision is not None:
            cursor = self.conn.execute(
                "SELECT * FROM run_completion_receipts WHERE run_id = ? AND revision = ?",
                (str(run_id), revision),
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM run_completion_receipts WHERE run_id = ? ORDER BY revision DESC LIMIT 1",
                (str(run_id),),
            )
        row = cursor.fetchone()
        return self._row_to_receipt(row) if row else None

    def list_receipts(self, run_id: uuid.UUID) -> list[RunCompletionReceipt]:
        """Fetch all receipt revisions for a run ID."""
        cursor = self.conn.execute(
            "SELECT * FROM run_completion_receipts WHERE run_id = ? ORDER BY revision ASC",
            (str(run_id),),
        )
        return [self._row_to_receipt(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Summary Delivery Outbox
    # -------------------------------------------------------------------------

    def save_delivery(self, delivery: SummaryDelivery) -> None:
        """Persist or update a SummaryDelivery entity."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_summary_deliveries (
                    delivery_id, run_id, org_id, completion_key, revision, state,
                    target_object, target_external_id_field, payload_json, payload_hash,
                    first_completion_hash, dispatch_attempts, reconcile_attempts,
                    retry_window_start, retry_deadline, next_due_at, remote_record_id,
                    acknowledged_revision, acknowledged_hash, notification_state,
                    notification_receipt_id, last_error_category, last_error_code,
                    last_error_message, claim_token, claimed_at, created_at, updated_at,
                    acknowledged_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, run_id) DO UPDATE SET
                    revision = excluded.revision,
                    state = excluded.state,
                    payload_json = excluded.payload_json,
                    payload_hash = excluded.payload_hash,
                    dispatch_attempts = excluded.dispatch_attempts,
                    reconcile_attempts = excluded.reconcile_attempts,
                    retry_window_start = excluded.retry_window_start,
                    retry_deadline = excluded.retry_deadline,
                    next_due_at = excluded.next_due_at,
                    remote_record_id = COALESCE(excluded.remote_record_id, run_summary_deliveries.remote_record_id),
                    acknowledged_revision = COALESCE(excluded.acknowledged_revision, run_summary_deliveries.acknowledged_revision),
                    acknowledged_hash = COALESCE(excluded.acknowledged_hash, run_summary_deliveries.acknowledged_hash),
                    notification_state = excluded.notification_state,
                    notification_receipt_id = COALESCE(excluded.notification_receipt_id, run_summary_deliveries.notification_receipt_id),
                    last_error_category = excluded.last_error_category,
                    last_error_code = excluded.last_error_code,
                    last_error_message = excluded.last_error_message,
                    claim_token = excluded.claim_token,
                    claimed_at = excluded.claimed_at,
                    updated_at = excluded.updated_at,
                    acknowledged_at = COALESCE(excluded.acknowledged_at, run_summary_deliveries.acknowledged_at)
                """,
                (
                    str(delivery.delivery_id),
                    str(delivery.run_id),
                    delivery.org_id,
                    delivery.completion_key,
                    delivery.revision,
                    delivery.state.value,
                    delivery.target_object,
                    delivery.target_external_id_field,
                    delivery.payload_json,
                    delivery.payload_hash,
                    delivery.first_completion_hash,
                    delivery.dispatch_attempts,
                    delivery.reconcile_attempts,
                    delivery.retry_window_start.isoformat(),
                    delivery.retry_deadline.isoformat(),
                    delivery.next_due_at.isoformat() if delivery.next_due_at else None,
                    delivery.remote_record_id,
                    delivery.acknowledged_revision,
                    delivery.acknowledged_hash,
                    delivery.notification_state.value,
                    delivery.notification_receipt_id,
                    delivery.last_error_category,
                    delivery.last_error_code,
                    delivery.last_error_message,
                    delivery.claim_token,
                    delivery.claimed_at.isoformat() if delivery.claimed_at else None,
                    delivery.created_at.isoformat(),
                    delivery.updated_at.isoformat(),
                    delivery.acknowledged_at.isoformat() if delivery.acknowledged_at else None,
                ),
            )

    def _row_to_delivery(self, row: sqlite3.Row) -> SummaryDelivery:
        return SummaryDelivery(
            delivery_id=uuid.UUID(row["delivery_id"]),
            run_id=uuid.UUID(row["run_id"]),
            org_id=row["org_id"],
            completion_key=row["completion_key"],
            revision=row["revision"],
            state=DeliveryState(row["state"]),
            target_object=row["target_object"],
            target_external_id_field=row["target_external_id_field"],
            payload_json=row["payload_json"],
            payload_hash=row["payload_hash"],
            first_completion_hash=row["first_completion_hash"],
            dispatch_attempts=row["dispatch_attempts"],
            reconcile_attempts=row["reconcile_attempts"],
            retry_window_start=datetime.fromisoformat(row["retry_window_start"]),
            retry_deadline=datetime.fromisoformat(row["retry_deadline"]),
            next_due_at=datetime.fromisoformat(row["next_due_at"]) if row["next_due_at"] else None,
            remote_record_id=row["remote_record_id"],
            acknowledged_revision=row["acknowledged_revision"],
            acknowledged_hash=row["acknowledged_hash"],
            notification_state=NotificationState(row["notification_state"]),
            notification_receipt_id=row["notification_receipt_id"],
            last_error_category=row["last_error_category"],
            last_error_code=row["last_error_code"],
            last_error_message=row["last_error_message"],
            claim_token=row["claim_token"],
            claimed_at=datetime.fromisoformat(row["claimed_at"]) if row["claimed_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
        )

    def get_delivery(self, org_id: str, run_id: uuid.UUID) -> SummaryDelivery | None:
        """Fetch delivery entity by Organization ID and Run UUID."""
        cursor = self.conn.execute(
            "SELECT * FROM run_summary_deliveries WHERE org_id = ? AND run_id = ?",
            (org_id, str(run_id)),
        )
        row = cursor.fetchone()
        return self._row_to_delivery(row) if row else None

    def get_delivery_by_run_id(self, run_id: uuid.UUID) -> SummaryDelivery | None:
        """Fetch delivery entity by Run UUID alone (convenience lookup)."""
        cursor = self.conn.execute(
            "SELECT * FROM run_summary_deliveries WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (str(run_id),),
        )
        row = cursor.fetchone()
        return self._row_to_delivery(row) if row else None

    def list_deliveries(
        self,
        state: DeliveryState | None = None,
        limit: int = 50,
    ) -> list[SummaryDelivery]:
        """List recent summary deliveries with optional state filter."""
        if state is not None:
            cursor = self.conn.execute(
                "SELECT * FROM run_summary_deliveries WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                (state.value, limit),
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM run_summary_deliveries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_delivery(row) for row in cursor.fetchall()]

    def claim_due_deliveries(
        self,
        org_id: str,
        claim_token: str,
        limit: int = 50,
        as_of: datetime | None = None,
    ) -> list[SummaryDelivery]:
        """Atomically claim due deliveries for dispatch.

        Claims work items in 'pending' or 'retry_wait' whose next_due_at is <= as_of.
        """
        now = as_of or datetime.now(timezone.utc)
        now_str = now.isoformat()

        with self.conn:
            # Select IDs of due work
            cursor = self.conn.execute(
                """
                SELECT delivery_id FROM run_summary_deliveries
                WHERE org_id = ?
                  AND state IN ('pending', 'retry_wait')
                  AND (next_due_at IS NULL OR next_due_at <= ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (org_id, now_str, limit),
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            delivery_ids = [row["delivery_id"] for row in rows]
            placeholders = ",".join("?" for _ in delivery_ids)

            # Atomically claim to in_flight
            self.conn.execute(
                f"""
                UPDATE run_summary_deliveries
                SET state = 'in_flight',
                    claim_token = ?,
                    claimed_at = ?,
                    updated_at = ?
                WHERE delivery_id IN ({placeholders})
                """,
                [claim_token, now_str, now_str] + delivery_ids,
            )

            # Retrieve updated records
            cursor = self.conn.execute(
                f"SELECT * FROM run_summary_deliveries WHERE delivery_id IN ({placeholders})",
                delivery_ids,
            )
            return [self._row_to_delivery(r) for r in cursor.fetchall()]

    def claim_stale_in_flight(
        self,
        org_id: str,
        stale_before: datetime,
    ) -> int:
        """Recover stale in_flight deliveries left by crashed workers into reconcile_required."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE run_summary_deliveries
                SET state = 'reconcile_required',
                    claim_token = NULL,
                    claimed_at = NULL,
                    updated_at = ?
                WHERE org_id = ?
                  AND state = 'in_flight'
                  AND claimed_at < ?
                """,
                (now_str, org_id, stale_before.isoformat()),
            )
            return cursor.rowcount

    # -------------------------------------------------------------------------
    # Delivery Attempts Audit
    # -------------------------------------------------------------------------

    def save_attempt(self, attempt: DeliveryAttemptRecord) -> None:
        """Record an attempt audit entry."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO run_summary_delivery_attempts (
                    attempt_id, delivery_id, run_id, attempt_sequence,
                    operation_kind, status, http_status, duration_ms,
                    remote_outcome, recovery_action, safe_error_code,
                    safe_error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(attempt.attempt_id),
                    str(attempt.delivery_id),
                    str(attempt.run_id),
                    attempt.attempt_sequence,
                    attempt.operation_kind,
                    attempt.status,
                    attempt.http_status,
                    attempt.duration_ms,
                    attempt.remote_outcome,
                    attempt.recovery_action,
                    attempt.safe_error_code,
                    attempt.safe_error_message,
                    attempt.created_at.isoformat(),
                ),
            )

    def list_attempts(self, delivery_id: uuid.UUID) -> list[DeliveryAttemptRecord]:
        """Fetch all attempt audits for a delivery."""
        cursor = self.conn.execute(
            """
            SELECT * FROM run_summary_delivery_attempts
            WHERE delivery_id = ?
            ORDER BY attempt_sequence ASC, created_at ASC
            """,
            (str(delivery_id),),
        )
        results: list[DeliveryAttemptRecord] = []
        for row in cursor.fetchall():
            results.append(
                DeliveryAttemptRecord(
                    attempt_id=uuid.UUID(row["attempt_id"]),
                    delivery_id=uuid.UUID(row["delivery_id"]),
                    run_id=uuid.UUID(row["run_id"]),
                    attempt_sequence=row["attempt_sequence"],
                    operation_kind=row["operation_kind"],
                    status=row["status"],
                    http_status=row["http_status"],
                    duration_ms=row["duration_ms"],
                    remote_outcome=row["remote_outcome"],
                    recovery_action=row["recovery_action"],
                    safe_error_code=row["safe_error_code"],
                    safe_error_message=row["safe_error_message"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return results

    # -------------------------------------------------------------------------
    # Scanner / Repair Queries
    # -------------------------------------------------------------------------

    def list_unregistered_terminal_receipts(
        self,
        org_id: str,
        cutoff_epoch: datetime | None = None,
        limit: int = 50,
    ) -> list[RunCompletionReceipt]:
        """Find committed terminal receipts that lack an outbox delivery entry for the given org."""
        query = """
            SELECT r.* FROM run_completion_receipts r
            LEFT JOIN run_summary_deliveries d
                ON r.run_id = d.run_id AND d.org_id = ?
            WHERE d.delivery_id IS NULL
        """
        params: list[Any] = [org_id]
        if cutoff_epoch is not None:
            query += " AND r.completed_at >= ?"
            params.append(cutoff_epoch.isoformat())

        query += " ORDER BY r.completed_at ASC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [self._row_to_receipt(row) for row in cursor.fetchall()]

