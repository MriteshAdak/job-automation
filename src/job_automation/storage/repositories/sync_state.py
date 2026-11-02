"""Durable repository for SYNC-01 plans, steps, ordering heads, and remote mappings."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import SyncOperationState
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.salesforce.sync_errors import (
    SyncBarrierError,
    SyncConflictError,
)
from job_automation.salesforce.sync_records import (
    EntityType,
    PublicationDecision,
    RemoteEntityMapping,
    SyncPlan,
    SyncStepState,
    SyncWriteStep,
)
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class SyncStateRepository(BaseRepository):
    """Manages plans, write steps, per-entity sequencing lanes, and remote entity mappings."""

    # -------------------------------------------------------------------------
    # Selection Heads
    # -------------------------------------------------------------------------

    def register_selection_token(
        self,
        canonical_job_id: uuid.UUID,
        generation_token: str,
    ) -> None:
        """Register or advance the active input-generation token for a job."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_selection_heads (
                    canonical_job_id, active_generation_token, registered_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(canonical_job_id) DO UPDATE SET
                    active_generation_token = excluded.active_generation_token,
                    updated_at = excluded.updated_at
                """,
                (str(canonical_job_id), generation_token, now_utc, now_utc),
            )

    def get_selection_token(self, canonical_job_id: uuid.UUID) -> str | None:
        """Get the current active input-generation token for a job."""
        cursor = self.conn.execute(
            "SELECT active_generation_token FROM sync_selection_heads WHERE canonical_job_id = ?",
            (str(canonical_job_id),),
        )
        row = cursor.fetchone()
        return str(row["active_generation_token"]) if row else None

    # -------------------------------------------------------------------------
    # Entity Ordering Lanes & Barriers
    # -------------------------------------------------------------------------

    def get_entity_head(
        self,
        org_id: str,
        target_object: str,
        entity_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Get current sequencing and barrier status for an entity lane."""
        cursor = self.conn.execute(
            """
            SELECT head_sequence, confirmed_sequence, locked_by, locked_until,
                   has_barrier, barrier_reason, updated_at
            FROM sync_entity_heads
            WHERE org_id = ? AND target_object = ? AND entity_id = ?
            """,
            (org_id, target_object, str(entity_id)),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def allocate_sequence(
        self,
        org_id: str,
        target_object: str,
        entity_id: uuid.UUID,
    ) -> int:
        """Atomically allocate the next monotonic sequence number for an entity lane."""
        now_utc = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """
            SELECT head_sequence FROM sync_entity_heads
            WHERE org_id = ? AND target_object = ? AND entity_id = ?
            """,
            (org_id, target_object, str(entity_id)),
        )
        row = cursor.fetchone()
        if not row:
            new_seq = 1
            self.conn.execute(
                """
                INSERT INTO sync_entity_heads (
                    org_id, target_object, entity_id, head_sequence,
                    confirmed_sequence, has_barrier, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, ?)
                """,
                (org_id, target_object, str(entity_id), new_seq, now_utc),
            )
            return new_seq
        else:
            current_head = int(row["head_sequence"])
            new_seq = current_head + 1
            self.conn.execute(
                """
                UPDATE sync_entity_heads
                SET head_sequence = ?, updated_at = ?
                WHERE org_id = ? AND target_object = ? AND entity_id = ?
                """,
                (new_seq, now_utc, org_id, target_object, str(entity_id)),
            )
            return new_seq

    def set_barrier(
        self,
        org_id: str,
        target_object: str,
        entity_id: uuid.UUID,
        reason: str,
    ) -> None:
        """Place an uncertainty/reconciliation barrier on an entity lane."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_entity_heads (
                    org_id, target_object, entity_id, head_sequence,
                    confirmed_sequence, has_barrier, barrier_reason, updated_at
                ) VALUES (?, ?, ?, 0, 0, 1, ?, ?)
                ON CONFLICT(org_id, target_object, entity_id) DO UPDATE SET
                    has_barrier = 1,
                    barrier_reason = excluded.barrier_reason,
                    updated_at = excluded.updated_at
                """,
                (org_id, target_object, str(entity_id), reason, now_utc),
            )

    def clear_barrier(
        self,
        org_id: str,
        target_object: str,
        entity_id: uuid.UUID,
    ) -> None:
        """Clear an uncertainty barrier from an entity lane."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                UPDATE sync_entity_heads
                SET has_barrier = 0, barrier_reason = NULL, updated_at = ?
                WHERE org_id = ? AND target_object = ? AND entity_id = ?
                """,
                (now_utc, org_id, target_object, str(entity_id)),
            )

    def has_active_barrier(
        self,
        org_id: str,
        target_object: str,
        entity_id: uuid.UUID,
    ) -> bool:
        """Check if an entity lane currently has an active barrier."""
        head = self.get_entity_head(org_id, target_object, entity_id)
        if not head:
            return False
        return bool(head.get("has_barrier", 0))

    # -------------------------------------------------------------------------
    # Remote Mappings
    # -------------------------------------------------------------------------

    def get_remote_mapping(
        self,
        org_id: str,
        target_object: str,
        entity_id: uuid.UUID,
    ) -> RemoteEntityMapping | None:
        """Get confirmed mapping for a canonical entity."""
        cursor = self.conn.execute(
            """
            SELECT org_id, target_object, entity_id, external_id, salesforce_id,
                   confirmed_sequence, reconciliation_marker, acknowledged_at
            FROM sync_remote_mappings
            WHERE org_id = ? AND target_object = ? AND entity_id = ?
            """,
            (org_id, target_object, str(entity_id)),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return RemoteEntityMapping(
            org_id=row["org_id"],
            object_name=row["target_object"],
            entity_id=uuid.UUID(row["entity_id"]),
            external_id=row["external_id"],
            salesforce_id=row["salesforce_id"],
            confirmed_sequence=row["confirmed_sequence"],
            reconciliation_marker=row["reconciliation_marker"],
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]),
        )

    def get_mapping_by_external_id(
        self,
        org_id: str,
        target_object: str,
        external_id: str,
    ) -> RemoteEntityMapping | None:
        """Get confirmed mapping by External ID value."""
        cursor = self.conn.execute(
            """
            SELECT org_id, target_object, entity_id, external_id, salesforce_id,
                   confirmed_sequence, reconciliation_marker, acknowledged_at
            FROM sync_remote_mappings
            WHERE org_id = ? AND target_object = ? AND external_id = ?
            """,
            (org_id, target_object, external_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return RemoteEntityMapping(
            org_id=row["org_id"],
            object_name=row["target_object"],
            entity_id=uuid.UUID(row["entity_id"]),
            external_id=row["external_id"],
            salesforce_id=row["salesforce_id"],
            confirmed_sequence=row["confirmed_sequence"],
            reconciliation_marker=row["reconciliation_marker"],
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]),
        )

    def save_remote_mapping(self, mapping: RemoteEntityMapping) -> None:
        """Upsert confirmed remote entity mapping."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_remote_mappings (
                    org_id, target_object, entity_id, external_id, salesforce_id,
                    confirmed_sequence, reconciliation_marker, acknowledged_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, target_object, entity_id) DO UPDATE SET
                    external_id = excluded.external_id,
                    salesforce_id = excluded.salesforce_id,
                    confirmed_sequence = max(sync_remote_mappings.confirmed_sequence, excluded.confirmed_sequence),
                    reconciliation_marker = excluded.reconciliation_marker,
                    acknowledged_at = excluded.acknowledged_at,
                    updated_at = excluded.updated_at
                """,
                (
                    mapping.org_id,
                    mapping.object_name,
                    str(mapping.entity_id),
                    mapping.external_id,
                    mapping.salesforce_id,
                    mapping.confirmed_sequence,
                    mapping.reconciliation_marker,
                    mapping.acknowledged_at.isoformat(),
                    now_utc,
                    now_utc,
                ),
            )

    # -------------------------------------------------------------------------
    # Atomic Plan & Steps Persistence
    # -------------------------------------------------------------------------

    def commit_plan_and_steps(
        self,
        plan: SyncPlan,
        sync_op: SyncOperation | None = None,
        assessment: Assessment | None = None,
    ) -> None:
        """Atomically persist assessment, sync operation, plan, and write steps in one transaction."""
        now_utc = datetime.now(timezone.utc).isoformat()

        try:
            with self.conn:
                # 1. Assessment (if provided and not yet stored)
                if assessment is not None:
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO assessments (
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

                # 2. SyncOperation (if provided)
                if sync_op is not None:
                    err_json = sync_op.error.model_dump_json() if sync_op.error else None
                    rem_ack = (
                        sync_op.remote_acknowledged_at.isoformat()
                        if sync_op.remote_acknowledged_at
                        else None
                    )
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

                # 3. SyncPlan
                self.conn.execute(
                    """
                    INSERT INTO sync_plans (
                        plan_id, canonical_job_id, assessment_id, mapping_version,
                        mapping_hash, plan_fingerprint, selection_token, run_id,
                        publication_decision, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(plan.plan_id),
                        str(plan.canonical_job_id),
                        str(plan.assessment_id),
                        plan.mapping_version,
                        plan.mapping_hash,
                        plan.plan_fingerprint,
                        plan.selection_token,
                        plan.run_id,
                        plan.publication_decision.value,
                        plan.created_at.isoformat(),
                    ),
                )

                # 4. SyncWriteSteps
                for step in plan.steps:
                    op_id = str(step.operation_id) if step.operation_id else None
                    dep_id = str(step.depends_on_step_id) if step.depends_on_step_id else None
                    err_step = step.error.model_dump_json() if step.error else None
                    next_att = step.next_attempt_at.isoformat() if step.next_attempt_at else None
                    rem_step_ack = (
                        step.acknowledged_at.isoformat() if step.acknowledged_at else None
                    )

                    self.conn.execute(
                        """
                        INSERT INTO sync_write_steps (
                            step_id, plan_id, operation_id, entity_type, entity_id,
                            sequence_number, target_object, external_id_field,
                            external_id_value, relationship_field, depends_on_step_id,
                            frozen_payload_json, step_fingerprint, state,
                            may_have_been_sent, attempt_count, next_attempt_at,
                            reconciliation_marker, remote_record_id, acknowledged_at,
                            error_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(step.step_id),
                            str(step.plan_id),
                            op_id,
                            step.entity_type.value,
                            str(step.entity_id),
                            step.sequence_number,
                            step.target_object,
                            step.external_id_field,
                            step.external_id_value,
                            step.relationship_field,
                            dep_id,
                            json.dumps(step.frozen_payload),
                            step.step_fingerprint,
                            step.state.value,
                            1 if step.may_have_been_sent else 0,
                            step.attempt_count,
                            next_att,
                            step.reconciliation_marker,
                            step.remote_record_id,
                            rem_step_ack,
                            err_step,
                            now_utc,
                            now_utc,
                        ),
                    )

        except sqlite3.IntegrityError as exc:
            msg = str(exc)
            if "UNIQUE constraint failed" in msg or "PRIMARY KEY" in msg:
                raise DuplicateKeyError(
                    f"Integrity constraint violation during atomic plan commit: {exc}",
                    constraint="sync_plan_integrity",
                ) from exc
            raise

    def get_plan(self, plan_id: uuid.UUID) -> SyncPlan | None:
        """Retrieve SyncPlan and its child write steps by plan UUID."""
        cursor = self.conn.execute(
            """
            SELECT plan_id, canonical_job_id, assessment_id, mapping_version,
                   mapping_hash, plan_fingerprint, selection_token, run_id,
                   publication_decision, created_at
            FROM sync_plans
            WHERE plan_id = ?
            """,
            (str(plan_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None

        steps = self.get_steps_for_plan(plan_id)
        return SyncPlan(
            plan_id=uuid.UUID(row["plan_id"]),
            canonical_job_id=uuid.UUID(row["canonical_job_id"]),
            assessment_id=uuid.UUID(row["assessment_id"]),
            mapping_version=row["mapping_version"],
            mapping_hash=row["mapping_hash"],
            plan_fingerprint=row["plan_fingerprint"],
            selection_token=row["selection_token"],
            run_id=row["run_id"],
            publication_decision=PublicationDecision(row["publication_decision"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            steps=steps,
        )

    def get_plan_by_fingerprint(
        self,
        canonical_job_id: uuid.UUID,
        plan_fingerprint: str,
    ) -> SyncPlan | None:
        """Find existing plan matching canonical job ID and plan fingerprint."""
        cursor = self.conn.execute(
            """
            SELECT plan_id FROM sync_plans
            WHERE canonical_job_id = ? AND plan_fingerprint = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (str(canonical_job_id), plan_fingerprint),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self.get_plan(uuid.UUID(row["plan_id"]))

    def get_plan_by_assessment(
        self,
        canonical_job_id: uuid.UUID,
        assessment_id: uuid.UUID,
    ) -> SyncPlan | None:
        """Find existing plan matching canonical job ID and assessment ID."""
        cursor = self.conn.execute(
            """
            SELECT plan_id FROM sync_plans
            WHERE canonical_job_id = ? AND assessment_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (str(canonical_job_id), str(assessment_id)),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self.get_plan(uuid.UUID(row["plan_id"]))

    def get_sync_operation(self, operation_id: uuid.UUID) -> SyncOperation | None:
        """Retrieve C12 SyncOperation by UUID."""
        cursor = self.conn.execute(
            """
            SELECT operation_id, canonical_job_id, payload_version,
                   payload_fingerprint, state, attempt_count, max_attempts,
                   remote_record_id, remote_acknowledged_at, error_json,
                   payload_json, created_at, updated_at
            FROM sync_operations
            WHERE operation_id = ?
            """,
            (str(operation_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        err = (
            ClassifiedError.model_validate_json(row["error_json"])
            if row["error_json"]
            else None
        )
        rem_ack = (
            datetime.fromisoformat(row["remote_acknowledged_at"])
            if row["remote_acknowledged_at"]
            else None
        )
        payload = SyncPayload.model_validate_json(row["payload_json"])
        return SyncOperation(
            operation_id=uuid.UUID(row["operation_id"]),
            canonical_job_id=uuid.UUID(row["canonical_job_id"]),
            payload_version=row["payload_version"],
            payload_fingerprint=row["payload_fingerprint"],
            state=SyncOperationState(row["state"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            remote_record_id=row["remote_record_id"],
            remote_acknowledged_at=rem_ack,
            error=err,
            locally_owned_payload=payload,
        )

    def get_latest_plan_for_job(self, canonical_job_id: uuid.UUID) -> SyncPlan | None:
        """Get the latest persisted SyncPlan for a job."""
        cursor = self.conn.execute(
            """
            SELECT plan_id FROM sync_plans
            WHERE canonical_job_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (str(canonical_job_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self.get_plan(uuid.UUID(row["plan_id"]))

    def get_steps_for_plan(self, plan_id: uuid.UUID) -> list[SyncWriteStep]:
        """Fetch all SyncWriteSteps belonging to a plan in sequence order."""
        cursor = self.conn.execute(
            """
            SELECT step_id, plan_id, operation_id, entity_type, entity_id,
                   sequence_number, target_object, external_id_field,
                   external_id_value, relationship_field, depends_on_step_id,
                   frozen_payload_json, step_fingerprint, state,
                   may_have_been_sent, attempt_count, next_attempt_at,
                   reconciliation_marker, remote_record_id, acknowledged_at,
                   error_json
            FROM sync_write_steps
            WHERE plan_id = ?
            ORDER BY sequence_number ASC, created_at ASC
            """,
            (str(plan_id),),
        )
        steps: list[SyncWriteStep] = []
        for r in cursor.fetchall():
            steps.append(self._row_to_step(r))
        return steps

    def get_step(self, step_id: uuid.UUID) -> SyncWriteStep | None:
        """Fetch a single write step by step UUID."""
        cursor = self.conn.execute(
            """
            SELECT step_id, plan_id, operation_id, entity_type, entity_id,
                   sequence_number, target_object, external_id_field,
                   external_id_value, relationship_field, depends_on_step_id,
                   frozen_payload_json, step_fingerprint, state,
                   may_have_been_sent, attempt_count, next_attempt_at,
                   reconciliation_marker, remote_record_id, acknowledged_at,
                   error_json
            FROM sync_write_steps
            WHERE step_id = ?
            """,
            (str(step_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_step(row)

    # -------------------------------------------------------------------------
    # Due Steps & Compare-and-Set Claims
    # -------------------------------------------------------------------------

    def get_due_steps(
        self,
        org_id: str,
        limit: int = 100,
        now_iso: str | None = None,
    ) -> list[SyncWriteStep]:
        """Fetch steps eligible for dispatch, respecting per-entity ordering and barriers."""
        ts = now_iso or datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """
            SELECT s.step_id, s.plan_id, s.operation_id, s.entity_type, s.entity_id,
                   s.sequence_number, s.target_object, s.external_id_field,
                   s.external_id_value, s.relationship_field, s.depends_on_step_id,
                   s.frozen_payload_json, s.step_fingerprint, s.state,
                   s.may_have_been_sent, s.attempt_count, s.next_attempt_at,
                   s.reconciliation_marker, s.remote_record_id, s.acknowledged_at,
                   s.error_json
            FROM sync_write_steps s
            WHERE s.state IN ('pending', 'retry_wait')
              AND (s.next_attempt_at IS NULL OR s.next_attempt_at <= ?)
              -- Exclude entities with active barrier
              AND NOT EXISTS (
                  SELECT 1 FROM sync_entity_heads h
                  WHERE h.org_id = ?
                    AND h.target_object = s.target_object
                    AND h.entity_id = s.entity_id
                    AND h.has_barrier = 1
              )
              -- Ensure parent dependency is satisfied (if present)
              AND (
                  s.depends_on_step_id IS NULL OR EXISTS (
                      SELECT 1 FROM sync_write_steps parent
                      WHERE parent.step_id = s.depends_on_step_id
                        AND parent.state = 'succeeded'
                  )
              )
            ORDER BY s.sequence_number ASC, s.created_at ASC
            LIMIT ?
            """,
            (ts, org_id, limit),
        )
        due: list[SyncWriteStep] = []
        for r in cursor.fetchall():
            due.append(self._row_to_step(r))
        return due

    def claim_step(
        self,
        step_id: uuid.UUID,
        worker_id: str,
        now_iso: str,
    ) -> bool:
        """Compare-and-set claim a step to RUNNING state and mark may_have_been_sent."""
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE sync_write_steps
                SET state = 'running',
                    may_have_been_sent = 1,
                    attempt_count = attempt_count + 1,
                    updated_at = ?
                WHERE step_id = ? AND state IN ('pending', 'retry_wait')
                """,
                (now_iso, str(step_id)),
            )
            return cursor.rowcount == 1

    def mark_step_succeeded(
        self,
        step_id: uuid.UUID,
        remote_record_id: str,
        acknowledged_at_iso: str,
        confirmed_sequence: int,
        org_id: str,
    ) -> None:
        """Mark step succeeded and advance entity confirmed sequence."""
        step = self.get_step(step_id)
        if not step:
            return

        with self.conn:
            # 1. Update step
            self.conn.execute(
                """
                UPDATE sync_write_steps
                SET state = 'succeeded',
                    remote_record_id = ?,
                    acknowledged_at = ?,
                    error_json = NULL,
                    updated_at = ?
                WHERE step_id = ?
                """,
                (remote_record_id, acknowledged_at_iso, acknowledged_at_iso, str(step_id)),
            )

            # 2. Advance confirmed sequence and clear barrier on entity head
            self.conn.execute(
                """
                INSERT INTO sync_entity_heads (
                    org_id, target_object, entity_id, head_sequence,
                    confirmed_sequence, has_barrier, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(org_id, target_object, entity_id) DO UPDATE SET
                    confirmed_sequence = max(sync_entity_heads.confirmed_sequence, excluded.confirmed_sequence),
                    has_barrier = 0,
                    barrier_reason = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    org_id,
                    step.target_object,
                    str(step.entity_id),
                    step.sequence_number,
                    confirmed_sequence,
                    acknowledged_at_iso,
                ),
            )

            # 3. If step has linked operation_id, update C12 sync_operations
            if step.operation_id is not None:
                self.conn.execute(
                    """
                    UPDATE sync_operations
                    SET state = 'succeeded',
                        remote_record_id = ?,
                        remote_acknowledged_at = ?,
                        error_json = NULL,
                        updated_at = ?
                    WHERE operation_id = ?
                    """,
                    (
                        remote_record_id,
                        acknowledged_at_iso,
                        acknowledged_at_iso,
                        str(step.operation_id),
                    ),
                )

    def mark_step_failed(
        self,
        step_id: uuid.UUID,
        error: ClassifiedError,
        next_attempt_at_iso: str | None,
        is_terminal: bool,
        retain_barrier: bool = False,
        barrier_reason: str | None = None,
        org_id: str | None = None,
    ) -> None:
        """Transition step to retry_wait or failed, with optional barrier placement."""
        step = self.get_step(step_id)
        if not step:
            return

        new_state = "failed" if is_terminal else "retry_wait"
        now_utc = datetime.now(timezone.utc).isoformat()
        err_json = error.model_dump_json()

        with self.conn:
            self.conn.execute(
                """
                UPDATE sync_write_steps
                SET state = ?,
                    next_attempt_at = ?,
                    error_json = ?,
                    updated_at = ?
                WHERE step_id = ?
                """,
                (new_state, next_attempt_at_iso, err_json, now_utc, str(step_id)),
            )

            # Update C12 operation if linked
            if step.operation_id is not None:
                self.conn.execute(
                    """
                    UPDATE sync_operations
                    SET state = ?,
                        error_json = ?,
                        updated_at = ?
                    WHERE operation_id = ?
                    """,
                    (new_state, err_json, now_utc, str(step.operation_id)),
                )

            # Retain uncertainty barrier if requested
            if retain_barrier and org_id is not None:
                b_reason = barrier_reason or "Step failed with uncertain remote transmission"
                self.set_barrier(org_id, step.target_object, step.entity_id, b_reason)

    def get_uncertain_steps(
        self,
        org_id: str,
        limit: int = 50,
    ) -> list[SyncWriteStep]:
        """Fetch steps that may have been transmitted but lack confirmed remote acknowledgment."""
        cursor = self.conn.execute(
            """
            SELECT s.step_id, s.plan_id, s.operation_id, s.entity_type, s.entity_id,
                   s.sequence_number, s.target_object, s.external_id_field,
                   s.external_id_value, s.relationship_field, s.depends_on_step_id,
                   s.frozen_payload_json, s.step_fingerprint, s.state,
                   s.may_have_been_sent, s.attempt_count, s.next_attempt_at,
                   s.reconciliation_marker, s.remote_record_id, s.acknowledged_at,
                   s.error_json
            FROM sync_write_steps s
            WHERE s.may_have_been_sent = 1
              AND s.acknowledged_at IS NULL
              AND s.state IN ('running', 'retry_wait', 'failed')
            ORDER BY s.sequence_number ASC, s.created_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        uncertain: list[SyncWriteStep] = []
        for r in cursor.fetchall():
            uncertain.append(self._row_to_step(r))
        return uncertain

    def supersede_step(self, step_id: uuid.UUID, reason: str) -> None:
        """Mark an older write step as superseded by a newer confirmed version."""
        now_utc = datetime.now(timezone.utc).isoformat()
        err = ClassifiedError.validation(f"Superseded by newer remote version: {reason}")
        with self.conn:
            self.conn.execute(
                """
                UPDATE sync_write_steps
                SET state = 'failed',
                    error_json = ?,
                    updated_at = ?
                WHERE step_id = ?
                """,
                (err.model_dump_json(), now_utc, str(step_id)),
            )

    def _row_to_step(self, r: sqlite3.Row) -> SyncWriteStep:
        err = (
            ClassifiedError.model_validate_json(r["error_json"])
            if r["error_json"]
            else None
        )
        next_att = (
            datetime.fromisoformat(r["next_attempt_at"])
            if r["next_attempt_at"]
            else None
        )
        ack_at = (
            datetime.fromisoformat(r["acknowledged_at"])
            if r["acknowledged_at"]
            else None
        )
        payload = json.loads(r["frozen_payload_json"])

        return SyncWriteStep(
            step_id=uuid.UUID(r["step_id"]),
            plan_id=uuid.UUID(r["plan_id"]),
            operation_id=uuid.UUID(r["operation_id"]) if r["operation_id"] else None,
            entity_type=EntityType(r["entity_type"]),
            entity_id=uuid.UUID(r["entity_id"]),
            sequence_number=r["sequence_number"],
            target_object=r["target_object"],
            external_id_field=r["external_id_field"],
            external_id_value=r["external_id_value"],
            relationship_field=r["relationship_field"],
            depends_on_step_id=(
                uuid.UUID(r["depends_on_step_id"]) if r["depends_on_step_id"] else None
            ),
            frozen_payload=payload,
            step_fingerprint=r["step_fingerprint"],
            state=SyncStepState(r["state"]),
            may_have_been_sent=bool(r["may_have_been_sent"]),
            attempt_count=r["attempt_count"],
            next_attempt_at=next_att,
            reconciliation_marker=r["reconciliation_marker"],
            remote_record_id=r["remote_record_id"],
            acknowledged_at=ack_at,
            error=err,
        )
