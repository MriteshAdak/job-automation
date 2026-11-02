"""Salesforce sync outbox repository and atomic transaction operations."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import SyncOperationState
from job_automation.contracts.sync import SyncOperation
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class SyncOutboxRepository(BaseRepository):
    """Manages C12 Salesforce SyncOperation outbox ledger and recovery.

    Guarantees atomic persistence of assessments with their corresponding
    outbox sync operations (blueprint §5).
    """

    def enqueue_operation(self, op: SyncOperation) -> None:
        """Enqueue a new Salesforce sync operation.

        Raises DuplicateKeyError if an operation with the same ID already exists.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        err_json = op.error.model_dump_json() if op.error else None
        rem_ack = op.remote_acknowledged_at.isoformat() if op.remote_acknowledged_at else None

        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO sync_operations (
                        operation_id, canonical_job_id, payload_version,
                        payload_fingerprint, state, attempt_count, max_attempts,
                        remote_record_id, remote_acknowledged_at, error_json,
                        payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(op.operation_id),
                        str(op.canonical_job_id),
                        op.payload_version,
                        op.payload_fingerprint,
                        op.state.value,
                        op.attempt_count,
                        op.max_attempts,
                        op.remote_record_id,
                        rem_ack,
                        err_json,
                        op.locally_owned_payload.model_dump_json(),
                        now_utc,
                        now_utc,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"Sync operation with ID '{op.operation_id}' already exists",
                    constraint="sync_operations_pk",
                ) from exc
            raise

    def get_operation(self, operation_id: uuid.UUID) -> SyncOperation | None:
        """Fetch sync operation by UUID."""
        cursor = self.conn.execute(
            """
            SELECT operation_id, canonical_job_id, payload_version,
                   payload_fingerprint, state, attempt_count, max_attempts,
                   remote_record_id, remote_acknowledged_at, error_json,
                   payload_json
            FROM sync_operations
            WHERE operation_id = ?
            """,
            (str(operation_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None

        from job_automation.contracts.errors import ClassifiedError
        from job_automation.contracts.sync import SyncPayload

        err = (
            ClassifiedError.model_validate_json(row["error_json"])
            if row["error_json"]
            else None
        )
        payload = SyncPayload.model_validate_json(row["payload_json"])
        rem_ack = (
            datetime.fromisoformat(row["remote_acknowledged_at"])
            if row["remote_acknowledged_at"]
            else None
        )

        return SyncOperation(
            operation_id=uuid.UUID(row["operation_id"]),
            canonical_job_id=uuid.UUID(row["canonical_job_id"]),
            payload_version=row["payload_version"],
            payload_fingerprint=row["payload_fingerprint"],
            locally_owned_payload=payload,
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            state=SyncOperationState(row["state"]),
            remote_record_id=row["remote_record_id"],
            remote_acknowledged_at=rem_ack,
            error=err,
        )

    def update_operation(self, op: SyncOperation) -> None:
        """Update state, attempts, error, and acknowledgment of a sync operation."""
        now_utc = datetime.now(timezone.utc).isoformat()
        err_json = op.error.model_dump_json() if op.error else None
        rem_ack = op.remote_acknowledged_at.isoformat() if op.remote_acknowledged_at else None

        with self.conn:
            self.conn.execute(
                """
                UPDATE sync_operations
                SET state = ?,
                    attempt_count = ?,
                    remote_record_id = ?,
                    remote_acknowledged_at = ?,
                    error_json = ?,
                    updated_at = ?
                WHERE operation_id = ?
                """,
                (
                    op.state.value,
                    op.attempt_count,
                    op.remote_record_id,
                    rem_ack,
                    err_json,
                    now_utc,
                    str(op.operation_id),
                ),
            )

    def get_pending_operations(self) -> list[SyncOperation]:
        """Fetch all operations currently in PENDING state."""
        cursor = self.conn.execute(
            "SELECT operation_id FROM sync_operations WHERE state = ? ORDER BY created_at ASC",
            (SyncOperationState.PENDING.value,),
        )
        results: list[SyncOperation] = []
        for row in cursor.fetchall():
            op = self.get_operation(uuid.UUID(row["operation_id"]))
            if op:
                results.append(op)
        return results

    def get_unfinished_operations(self) -> list[SyncOperation]:
        """Fetch all operations requiring work or in-flight (pending, running, retry_wait)."""
        cursor = self.conn.execute(
            """
            SELECT operation_id FROM sync_operations
            WHERE state IN (?, ?, ?)
            ORDER BY created_at ASC
            """,
            (
                SyncOperationState.PENDING.value,
                SyncOperationState.RUNNING.value,
                SyncOperationState.RETRY_WAIT.value,
            ),
        )
        results: list[SyncOperation] = []
        for row in cursor.fetchall():
            op = self.get_operation(uuid.UUID(row["operation_id"]))
            if op:
                results.append(op)
        return results

    def recover_stale_running(self) -> list[SyncOperation]:
        """Reset interrupted RUNNING operations to RETRY_WAIT upon process recovery."""
        unfinished = self.get_unfinished_operations()
        recovered: list[SyncOperation] = []
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.conn:
            for op in unfinished:
                if op.state == SyncOperationState.RUNNING:
                    self.conn.execute(
                        """
                        UPDATE sync_operations
                        SET state = ?, updated_at = ?
                        WHERE operation_id = ?
                        """,
                        (SyncOperationState.RETRY_WAIT.value, now_utc, str(op.operation_id)),
                    )
                    recovered.append(op)

        return recovered

    def atomic_commit_assessment_and_sync(
        self,
        assessment: Assessment,
        sync_op: SyncOperation,
    ) -> None:
        """Atomically commit an assessment and its pending Salesforce write (blueprint §5).

        If either insert fails, the entire transaction rolls back.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        err_json = sync_op.error.model_dump_json() if sync_op.error else None
        rem_ack = (
            sync_op.remote_acknowledged_at.isoformat()
            if sync_op.remote_acknowledged_at
            else None
        )

        try:
            with self.conn:
                # 1. Insert assessment
                self.conn.execute(
                    """
                    INSERT INTO assessments (
                        assessment_id, canonical_job_id, posting_revision,
                        profile_version, policy_version, assessment_method,
                        relevance_decision, relevance_score, final_disposition,
                        summary_reason, assessment_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(assessment.assessment_id),
                        str(assessment.canonical_job_id),
                        assessment.posting_revision,
                        assessment.profile_version,
                        assessment.policy_version,
                        assessment.assessment_method.value,
                        assessment.relevance_decision.value,
                        assessment.relevance_score,
                        assessment.final_disposition.value,
                        assessment.summary_reason,
                        assessment.model_dump_json(),
                        now_utc,
                    ),
                )

                # 2. Insert sync operation
                self.conn.execute(
                    """
                    INSERT INTO sync_operations (
                        operation_id, canonical_job_id, payload_version,
                        payload_fingerprint, state, attempt_count, max_attempts,
                        remote_record_id, remote_acknowledged_at, error_json,
                        payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(sync_op.operation_id),
                        str(sync_op.canonical_job_id),
                        sync_op.payload_version,
                        sync_op.payload_fingerprint,
                        sync_op.state.value,
                        sync_op.attempt_count,
                        sync_op.max_attempts,
                        sync_op.remote_record_id,
                        rem_ack,
                        err_json,
                        sync_op.locally_owned_payload.model_dump_json(),
                        now_utc,
                        now_utc,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"Integrity constraint violation during atomic assessment/sync commit: {exc}"
                ) from exc
            raise

