"""Generation workflow companion repository for observations, freeze associations, checkpoints, and intents."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from job_automation.contracts.enums import ContextStrategy, GenerationProcessing
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.generation.errors import FreezeConflictError, InvalidRequestStateError
from job_automation.generation.records import (
    ArtifactDeliveryRecord,
    FreezeManifest,
    GenerationRequestObservation,
    ObservationIssueCategory,
    ProjectionIntent,
    ProjectionStatus,
    StageAttempt,
    StageCheckpoint,
    StageStatus,
)
from job_automation.storage.connection import _TRANSACTION_DEPTHS, transaction
from job_automation.storage.exceptions import DuplicateKeyError, RecordNotFoundError
from job_automation.storage.repositories.base import BaseRepository


class GenerationWorkRepository(BaseRepository):
    """Manages GEN-01 companion records, stage receipts, and atomic freeze transitions."""

    def _execute(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        """Execute a statement safely, respecting outer transactions if active."""
        depth = _TRANSACTION_DEPTHS.get(id(self.conn), 0)
        if depth > 0:
            return self.conn.execute(sql, params)
        with self.conn:
            return self.conn.execute(sql, params)

    # -------------------------------------------------------------------------
    # Observations
    # -------------------------------------------------------------------------

    def save_observation(self, observation: GenerationRequestObservation) -> None:
        """Persist or update a remote generation request observation."""
        self._execute(
            """
            INSERT INTO generation_request_observations (
                observation_id, org_id, salesforce_request_id, canonical_salesforce_id,
                client_request_key, local_request_id, canonical_job_id, remote_state,
                observed_options_digest, observed_at, remote_updated_at, issue_category,
                issue_message, raw_record_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(observation_id) DO UPDATE SET
                remote_state = excluded.remote_state,
                local_request_id = excluded.local_request_id,
                canonical_job_id = excluded.canonical_job_id,
                observed_options_digest = excluded.observed_options_digest,
                observed_at = excluded.observed_at,
                remote_updated_at = excluded.remote_updated_at,
                issue_category = excluded.issue_category,
                issue_message = excluded.issue_message,
                raw_record_json = excluded.raw_record_json
            """,
            (
                str(observation.observation_id),
                observation.org_id,
                observation.salesforce_request_id,
                observation.canonical_salesforce_id,
                observation.client_request_key,
                str(observation.local_request_id) if observation.local_request_id else None,
                str(observation.canonical_job_id) if observation.canonical_job_id else None,
                observation.remote_state,
                observation.observed_options_digest,
                observation.observed_at.isoformat(),
                observation.remote_updated_at.isoformat() if observation.remote_updated_at else None,
                observation.issue_category.value if observation.issue_category else None,
                observation.issue_message,
                json.dumps(observation.raw_record),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def get_observation(self, observation_id: uuid.UUID) -> GenerationRequestObservation | None:
        """Fetch an observation by UUID."""
        cursor = self.conn.execute(
            """
            SELECT observation_id, org_id, salesforce_request_id, canonical_salesforce_id,
                   client_request_key, local_request_id, canonical_job_id, remote_state,
                   observed_options_digest, observed_at, remote_updated_at, issue_category,
                   issue_message, raw_record_json
            FROM generation_request_observations
            WHERE observation_id = ?
            """,
            (str(observation_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_observation(row)

    def get_observation_by_salesforce_id(
        self, org_id: str, canonical_sf_id: str
    ) -> GenerationRequestObservation | None:
        """Fetch latest observation for a specific Salesforce request in an org."""
        cursor = self.conn.execute(
            """
            SELECT observation_id, org_id, salesforce_request_id, canonical_salesforce_id,
                   client_request_key, local_request_id, canonical_job_id, remote_state,
                   observed_options_digest, observed_at, remote_updated_at, issue_category,
                   issue_message, raw_record_json
            FROM generation_request_observations
            WHERE org_id = ? AND canonical_salesforce_id = ?
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            (org_id, canonical_sf_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_observation(row)

    def list_observations(self, limit: int = 100) -> list[GenerationRequestObservation]:
        """List recent observations."""
        cursor = self.conn.execute(
            """
            SELECT observation_id, org_id, salesforce_request_id, canonical_salesforce_id,
                   client_request_key, local_request_id, canonical_job_id, remote_state,
                   observed_options_digest, observed_at, remote_updated_at, issue_category,
                   issue_message, raw_record_json
            FROM generation_request_observations
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_observation(r) for r in cursor.fetchall()]

    def _row_to_observation(self, row: sqlite3.Row) -> GenerationRequestObservation:
        return GenerationRequestObservation(
            observation_id=uuid.UUID(row["observation_id"]),
            org_id=row["org_id"],
            salesforce_request_id=row["salesforce_request_id"],
            canonical_salesforce_id=row["canonical_salesforce_id"],
            client_request_key=row["client_request_key"],
            local_request_id=uuid.UUID(row["local_request_id"]) if row["local_request_id"] else None,
            canonical_job_id=uuid.UUID(row["canonical_job_id"]) if row["canonical_job_id"] else None,
            remote_state=row["remote_state"],
            observed_options_digest=row["observed_options_digest"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            remote_updated_at=datetime.fromisoformat(row["remote_updated_at"]) if row["remote_updated_at"] else None,
            issue_category=ObservationIssueCategory(row["issue_category"]) if row["issue_category"] else None,
            issue_message=row["issue_message"],
            raw_record=json.loads(row["raw_record_json"]),
        )

    # -------------------------------------------------------------------------
    # Freeze Associations
    # -------------------------------------------------------------------------

    def save_freeze_association(self, request_id: uuid.UUID, manifest: FreezeManifest) -> None:
        """Persist a sealed freeze manifest association."""
        self._execute(
            """
            INSERT INTO generation_freeze_associations (
                request_id, manifest_id, manifest_hash, canonical_job_id,
                posting_revision_id, posting_revision_hash, profile_version,
                policy_version, template_id, template_version, context_strategy,
                target_language, options_digest, availability_status,
                allow_unavailable_job, frozen_at, manifest_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(request_id),
                manifest.manifest_id,
                manifest.manifest_hash,
                str(manifest.canonical_job_id),
                manifest.posting_revision_id,
                manifest.posting_revision_hash,
                manifest.profile_version,
                manifest.policy_version,
                manifest.template_id,
                manifest.template_version,
                manifest.context_strategy.value,
                manifest.target_language,
                manifest.options_digest,
                manifest.availability_status,
                1 if manifest.allow_unavailable_job else 0,
                manifest.frozen_at.isoformat(),
                manifest.model_dump_json(),
            ),
        )

    def get_freeze_association(self, request_id: uuid.UUID) -> FreezeManifest | None:
        """Fetch the sealed freeze manifest for a request."""
        cursor = self.conn.execute(
            "SELECT manifest_json FROM generation_freeze_associations WHERE request_id = ?",
            (str(request_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return FreezeManifest.model_validate_json(row["manifest_json"])

    # -------------------------------------------------------------------------
    # Checkpoints
    # -------------------------------------------------------------------------

    def save_checkpoint(self, checkpoint: StageCheckpoint) -> None:
        """Persist or update a stage checkpoint receipt."""
        err_json = checkpoint.error.model_dump_json() if checkpoint.error else None
        completed_str = checkpoint.completed_at.isoformat() if checkpoint.completed_at else None

        self._execute(
            """
            INSERT INTO generation_request_checkpoints (
                checkpoint_id, request_id, stage_name, stage_operation_id,
                checkpoint_revision, status, started_at, completed_at,
                output_ref, output_hash, error_json, checkpoint_data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id, stage_name) DO UPDATE SET
                checkpoint_id = excluded.checkpoint_id,
                stage_operation_id = excluded.stage_operation_id,
                checkpoint_revision = excluded.checkpoint_revision,
                status = excluded.status,
                completed_at = excluded.completed_at,
                output_ref = excluded.output_ref,
                output_hash = excluded.output_hash,
                error_json = excluded.error_json,
                checkpoint_data_json = excluded.checkpoint_data_json
            """,
            (
                str(checkpoint.checkpoint_id),
                str(checkpoint.request_id),
                checkpoint.stage_name,
                checkpoint.stage_operation_id,
                checkpoint.checkpoint_revision,
                checkpoint.status.value,
                checkpoint.started_at.isoformat(),
                completed_str,
                checkpoint.output_ref,
                checkpoint.output_hash,
                err_json,
                json.dumps(checkpoint.checkpoint_data),
            ),
        )

    def get_checkpoint(self, request_id: uuid.UUID, stage_name: str) -> StageCheckpoint | None:
        """Fetch checkpoint for a specific stage of a request."""
        cursor = self.conn.execute(
            """
            SELECT checkpoint_id, request_id, stage_name, stage_operation_id,
                   checkpoint_revision, status, started_at, completed_at,
                   output_ref, output_hash, error_json, checkpoint_data_json
            FROM generation_request_checkpoints
            WHERE request_id = ? AND stage_name = ?
            """,
            (str(request_id), stage_name),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_checkpoint(row)

    def list_checkpoints(self, request_id: uuid.UUID) -> list[StageCheckpoint]:
        """List all stage checkpoints for a request."""
        cursor = self.conn.execute(
            """
            SELECT checkpoint_id, request_id, stage_name, stage_operation_id,
                   checkpoint_revision, status, started_at, completed_at,
                   output_ref, output_hash, error_json, checkpoint_data_json
            FROM generation_request_checkpoints
            WHERE request_id = ?
            ORDER BY started_at ASC
            """,
            (str(request_id),),
        )
        return [self._row_to_checkpoint(r) for r in cursor.fetchall()]

    def _row_to_checkpoint(self, row: sqlite3.Row) -> StageCheckpoint:
        err = ClassifiedError.model_validate_json(row["error_json"]) if row["error_json"] else None
        return StageCheckpoint(
            checkpoint_id=uuid.UUID(row["checkpoint_id"]),
            request_id=uuid.UUID(row["request_id"]),
            stage_name=row["stage_name"],
            stage_operation_id=row["stage_operation_id"],
            checkpoint_revision=row["checkpoint_revision"],
            status=StageStatus(row["status"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            output_ref=row["output_ref"],
            output_hash=row["output_hash"],
            error=err,
            checkpoint_data=json.loads(row["checkpoint_data_json"]),
        )

    # -------------------------------------------------------------------------
    # Physical Attempts
    # -------------------------------------------------------------------------

    def record_attempt(self, attempt: StageAttempt) -> None:
        """Record an attempt execution audit entry."""
        err_json = attempt.error.model_dump_json() if attempt.error else None
        completed_str = attempt.completed_at.isoformat() if attempt.completed_at else None

        self._execute(
            """
            INSERT INTO generation_request_attempts (
                attempt_id, request_id, stage_name, stage_operation_id,
                attempt_sequence, worker_attempt_id, status, started_at,
                completed_at, error_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(attempt.attempt_id),
                str(attempt.request_id),
                attempt.stage_name,
                attempt.stage_operation_id,
                attempt.attempt_sequence,
                str(attempt.worker_attempt_id),
                attempt.status.value,
                attempt.started_at.isoformat(),
                completed_str,
                err_json,
            ),
        )

    def list_attempts(
        self, request_id: uuid.UUID, stage_name: str | None = None
    ) -> list[StageAttempt]:
        """List execution attempts for a request, optionally filtered by stage."""
        if stage_name:
            cursor = self.conn.execute(
                """
                SELECT attempt_id, request_id, stage_name, stage_operation_id,
                       attempt_sequence, worker_attempt_id, status, started_at,
                       completed_at, error_json
                FROM generation_request_attempts
                WHERE request_id = ? AND stage_name = ?
                ORDER BY attempt_sequence ASC
                """,
                (str(request_id), stage_name),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT attempt_id, request_id, stage_name, stage_operation_id,
                       attempt_sequence, worker_attempt_id, status, started_at,
                       completed_at, error_json
                FROM generation_request_attempts
                WHERE request_id = ?
                ORDER BY attempt_sequence ASC
                """,
                (str(request_id),),
            )
        return [
            StageAttempt(
                attempt_id=uuid.UUID(r["attempt_id"]),
                request_id=uuid.UUID(r["request_id"]),
                stage_name=r["stage_name"],
                stage_operation_id=r["stage_operation_id"],
                attempt_sequence=r["attempt_sequence"],
                worker_attempt_id=uuid.UUID(r["worker_attempt_id"]),
                status=StageStatus(r["status"]),
                started_at=datetime.fromisoformat(r["started_at"]),
                completed_at=datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
                error=ClassifiedError.model_validate_json(r["error_json"]) if r["error_json"] else None,
            )
            for r in cursor.fetchall()
        ]

    # -------------------------------------------------------------------------
    # Projection Intents
    # -------------------------------------------------------------------------

    def save_projection_intent(self, intent: ProjectionIntent) -> None:
        """Persist a new projection intent."""
        err_json = intent.last_error.model_dump_json() if intent.last_error else None
        ack_str = intent.acknowledged_at.isoformat() if intent.acknowledged_at else None
        unc_str = intent.uncertain_at.isoformat() if intent.uncertain_at else None

        self._execute(
            """
            INSERT INTO generation_projection_intents (
                intent_id, request_id, projection_revision, operation_marker,
                desired_remote_state, expected_remote_state, payload_json,
                status, attempts, created_at, updated_at, acknowledged_at,
                uncertain_at, last_error_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id, projection_revision) DO UPDATE SET
                operation_marker = excluded.operation_marker,
                desired_remote_state = excluded.desired_remote_state,
                expected_remote_state = excluded.expected_remote_state,
                payload_json = excluded.payload_json,
                status = excluded.status,
                attempts = excluded.attempts,
                updated_at = excluded.updated_at,
                acknowledged_at = excluded.acknowledged_at,
                uncertain_at = excluded.uncertain_at,
                last_error_json = excluded.last_error_json
            """,
            (
                str(intent.intent_id),
                str(intent.request_id),
                intent.projection_revision,
                intent.operation_marker,
                intent.desired_remote_state,
                intent.expected_remote_state,
                json.dumps(intent.payload),
                intent.status.value,
                intent.attempts,
                intent.created_at.isoformat(),
                intent.updated_at.isoformat(),
                ack_str,
                unc_str,
                err_json,
            ),
        )

    def get_projection_intent(
        self, request_id: uuid.UUID, revision: int
    ) -> ProjectionIntent | None:
        """Fetch projection intent by request and revision."""
        cursor = self.conn.execute(
            """
            SELECT intent_id, request_id, projection_revision, operation_marker,
                   desired_remote_state, expected_remote_state, payload_json,
                   status, attempts, created_at, updated_at, acknowledged_at,
                   uncertain_at, last_error_json
            FROM generation_projection_intents
            WHERE request_id = ? AND projection_revision = ?
            """,
            (str(request_id), revision),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_intent(row)

    def get_active_projection_intent(self, request_id: uuid.UUID) -> ProjectionIntent | None:
        """Fetch the latest projection intent for a request."""
        cursor = self.conn.execute(
            """
            SELECT intent_id, request_id, projection_revision, operation_marker,
                   desired_remote_state, expected_remote_state, payload_json,
                   status, attempts, created_at, updated_at, acknowledged_at,
                   uncertain_at, last_error_json
            FROM generation_projection_intents
            WHERE request_id = ?
            ORDER BY projection_revision DESC
            LIMIT 1
            """,
            (str(request_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_intent(row)

    def list_unacknowledged_intents(self) -> list[ProjectionIntent]:
        """Fetch all projection intents in pending, sending, or uncertain status."""
        cursor = self.conn.execute(
            """
            SELECT intent_id, request_id, projection_revision, operation_marker,
                   desired_remote_state, expected_remote_state, payload_json,
                   status, attempts, created_at, updated_at, acknowledged_at,
                   uncertain_at, last_error_json
            FROM generation_projection_intents
            WHERE status IN (?, ?, ?)
            ORDER BY created_at ASC
            """,
            (
                ProjectionStatus.PENDING.value,
                ProjectionStatus.SENDING.value,
                ProjectionStatus.UNCERTAIN.value,
            ),
        )
        return [self._row_to_intent(r) for r in cursor.fetchall()]

    def update_projection_intent(self, intent: ProjectionIntent) -> None:
        """Update status, attempts, error, and timestamps for an intent."""
        self.save_projection_intent(intent)

    def _row_to_intent(self, row: sqlite3.Row) -> ProjectionIntent:
        err = ClassifiedError.model_validate_json(row["last_error_json"]) if row["last_error_json"] else None
        return ProjectionIntent(
            intent_id=uuid.UUID(row["intent_id"]),
            request_id=uuid.UUID(row["request_id"]),
            projection_revision=row["projection_revision"],
            operation_marker=row["operation_marker"],
            desired_remote_state=row["desired_remote_state"],
            expected_remote_state=row["expected_remote_state"],
            payload=json.loads(row["payload_json"]),
            status=ProjectionStatus(row["status"]),
            attempts=row["attempts"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
            uncertain_at=datetime.fromisoformat(row["uncertain_at"]) if row["uncertain_at"] else None,
            last_error=err,
        )

    # -------------------------------------------------------------------------
    # Artifact Deliveries
    # -------------------------------------------------------------------------

    def save_delivery_record(self, record: ArtifactDeliveryRecord) -> None:
        """Persist or update an artifact delivery slot receipt."""
        deliv_str = record.delivered_at.isoformat() if record.delivered_at else None
        self._execute(
            """
            INSERT INTO generation_artifact_deliveries (
                delivery_id, request_id, artifact_format, artifact_id,
                artifact_hash, remote_file_id, delivery_status, delivered_at,
                receipt_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id, artifact_format) DO UPDATE SET
                artifact_id = excluded.artifact_id,
                artifact_hash = excluded.artifact_hash,
                remote_file_id = excluded.remote_file_id,
                delivery_status = excluded.delivery_status,
                delivered_at = excluded.delivered_at,
                receipt_json = excluded.receipt_json
            """,
            (
                str(record.delivery_id),
                str(record.request_id),
                record.artifact_format,
                str(record.artifact_id),
                record.artifact_hash,
                record.remote_file_id,
                record.delivery_status,
                deliv_str,
                json.dumps(record.receipt_data),
            ),
        )

    def get_delivery_record(
        self, request_id: uuid.UUID, artifact_format: str
    ) -> ArtifactDeliveryRecord | None:
        """Fetch delivery record for a specific format slot."""
        cursor = self.conn.execute(
            """
            SELECT delivery_id, request_id, artifact_format, artifact_id,
                   artifact_hash, remote_file_id, delivery_status, delivered_at,
                   receipt_json
            FROM generation_artifact_deliveries
            WHERE request_id = ? AND artifact_format = ?
            """,
            (str(request_id), artifact_format),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ArtifactDeliveryRecord(
            delivery_id=uuid.UUID(row["delivery_id"]),
            request_id=uuid.UUID(row["request_id"]),
            artifact_format=row["artifact_format"],
            artifact_id=uuid.UUID(row["artifact_id"]),
            artifact_hash=row["artifact_hash"],
            remote_file_id=row["remote_file_id"],
            delivery_status=row["delivery_status"],
            delivered_at=datetime.fromisoformat(row["delivered_at"]) if row["delivered_at"] else None,
            receipt_data=json.loads(row["receipt_json"]),
        )

    def list_delivery_records(self, request_id: uuid.UUID) -> list[ArtifactDeliveryRecord]:
        """List all delivery slot records for a request."""
        cursor = self.conn.execute(
            """
            SELECT delivery_id, request_id, artifact_format, artifact_id,
                   artifact_hash, remote_file_id, delivery_status, delivered_at,
                   receipt_json
            FROM generation_artifact_deliveries
            WHERE request_id = ?
            ORDER BY artifact_format ASC
            """,
            (str(request_id),),
        )
        return [
            ArtifactDeliveryRecord(
                delivery_id=uuid.UUID(row["delivery_id"]),
                request_id=uuid.UUID(row["request_id"]),
                artifact_format=row["artifact_format"],
                artifact_id=uuid.UUID(row["artifact_id"]),
                artifact_hash=row["artifact_hash"],
                remote_file_id=row["remote_file_id"],
                delivery_status=row["delivery_status"],
                delivered_at=datetime.fromisoformat(row["delivered_at"]) if row["delivered_at"] else None,
                receipt_data=json.loads(row["receipt_json"]),
            )
            for row in cursor.fetchall()
        ]

    # -------------------------------------------------------------------------
    # Atomic Freeze Commitment
    # -------------------------------------------------------------------------

    def commit_frozen_request(
        self,
        request: GenerationRequest,
        manifest: FreezeManifest,
        checkpoint: StageCheckpoint,
        projection_intent: ProjectionIntent,
    ) -> None:
        """Atomically commit request claim, freeze association, checkpoint, and Running projection intent.

        Guarantees:
        - Commits in ONE atomic transaction.
        - Verifies freeze-once invariance: raises FreezeConflictError if request was already frozen
          with different options or manifest.
        - Synchronizes indexed columns with request JSON.
        - If any statement fails, all changes roll back.
        """
        existing_freeze = self.get_freeze_association(request.request_id)
        if existing_freeze is not None:
            if (
                existing_freeze.manifest_hash != manifest.manifest_hash
                or existing_freeze.options_digest != manifest.options_digest
            ):
                raise FreezeConflictError(
                    f"Request {request.request_id} is already frozen with different manifest/options "
                    f"(existing: {existing_freeze.manifest_hash}, new: {manifest.manifest_hash})"
                )
            # Idempotent replay: already committed with exact same manifest
            return

        with transaction(self.conn):
            # Verify durable seal if present in generation_frozen_seals
            try:
                seal_cur = self.conn.execute(
                    "SELECT manifest_hash, options_digest FROM generation_frozen_seals WHERE request_id = ?",
                    (str(request.request_id),),
                )
                seal_row = seal_cur.fetchone()
                if seal_row is not None and seal_row["manifest_hash"] != manifest.manifest_hash:
                    raise FreezeConflictError(
                        f"Seal manifest hash mismatch for request {request.request_id}: "
                        f"sealed={seal_row['manifest_hash']}, claiming={manifest.manifest_hash}"
                    )
            except sqlite3.OperationalError:
                pass

            # 1. Update generation_requests
            frozen_json = (
                request.frozen_input_versions.model_dump_json()
                if request.frozen_input_versions
                else None
            )
            claimed_str = request.claimed_at.isoformat() if request.claimed_at else None
            completed_str = request.completed_at.isoformat() if request.completed_at else None
            err_json = request.error.model_dump_json() if request.error else None

            self.conn.execute(
                """
                UPDATE generation_requests
                SET state = ?,
                    claimed_at = ?,
                    completed_at = ?,
                    frozen_inputs_json = ?,
                    result_artifact_ref = ?,
                    error_json = ?,
                    request_json = ?
                WHERE request_id = ?
                """,
                (
                    request.state.value,
                    claimed_str,
                    completed_str,
                    frozen_json,
                    request.result_artifact_ref,
                    err_json,
                    request.model_dump_json(),
                    str(request.request_id),
                ),
            )

            # 2. Insert freeze association
            self.conn.execute(
                """
                INSERT INTO generation_freeze_associations (
                    request_id, manifest_id, manifest_hash, canonical_job_id,
                    posting_revision_id, posting_revision_hash, profile_version,
                    policy_version, template_id, template_version, context_strategy,
                    target_language, options_digest, availability_status,
                    allow_unavailable_job, frozen_at, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(request.request_id),
                    manifest.manifest_id,
                    manifest.manifest_hash,
                    str(manifest.canonical_job_id),
                    manifest.posting_revision_id,
                    manifest.posting_revision_hash,
                    manifest.profile_version,
                    manifest.policy_version,
                    manifest.template_id,
                    manifest.template_version,
                    manifest.context_strategy.value,
                    manifest.target_language,
                    manifest.options_digest,
                    manifest.availability_status,
                    1 if manifest.allow_unavailable_job else 0,
                    manifest.frozen_at.isoformat(),
                    manifest.model_dump_json(),
                ),
            )

            # 3. Save freeze checkpoint receipt
            chk_err = checkpoint.error.model_dump_json() if checkpoint.error else None
            chk_comp = checkpoint.completed_at.isoformat() if checkpoint.completed_at else None
            self.conn.execute(
                """
                INSERT INTO generation_request_checkpoints (
                    checkpoint_id, request_id, stage_name, stage_operation_id,
                    checkpoint_revision, status, started_at, completed_at,
                    output_ref, output_hash, error_json, checkpoint_data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, stage_name) DO UPDATE SET
                    checkpoint_id = excluded.checkpoint_id,
                    stage_operation_id = excluded.stage_operation_id,
                    checkpoint_revision = excluded.checkpoint_revision,
                    status = excluded.status,
                    completed_at = excluded.completed_at,
                    output_ref = excluded.output_ref,
                    output_hash = excluded.output_hash,
                    error_json = excluded.error_json,
                    checkpoint_data_json = excluded.checkpoint_data_json
                """,
                (
                    str(checkpoint.checkpoint_id),
                    str(checkpoint.request_id),
                    checkpoint.stage_name,
                    checkpoint.stage_operation_id,
                    checkpoint.checkpoint_revision,
                    checkpoint.status.value,
                    checkpoint.started_at.isoformat(),
                    chk_comp,
                    checkpoint.output_ref,
                    checkpoint.output_hash,
                    chk_err,
                    json.dumps(checkpoint.checkpoint_data),
                ),
            )

            # 4. Save Running projection intent
            intent_err = projection_intent.last_error.model_dump_json() if projection_intent.last_error else None
            intent_ack = projection_intent.acknowledged_at.isoformat() if projection_intent.acknowledged_at else None
            intent_unc = projection_intent.uncertain_at.isoformat() if projection_intent.uncertain_at else None
            self.conn.execute(
                """
                INSERT INTO generation_projection_intents (
                    intent_id, request_id, projection_revision, operation_marker,
                    desired_remote_state, expected_remote_state, payload_json,
                    status, attempts, created_at, updated_at, acknowledged_at,
                    uncertain_at, last_error_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, projection_revision) DO UPDATE SET
                    operation_marker = excluded.operation_marker,
                    desired_remote_state = excluded.desired_remote_state,
                    expected_remote_state = excluded.expected_remote_state,
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    attempts = excluded.attempts,
                    updated_at = excluded.updated_at,
                    acknowledged_at = excluded.acknowledged_at,
                    uncertain_at = excluded.uncertain_at,
                    last_error_json = excluded.last_error_json
                """,
                (
                    str(projection_intent.intent_id),
                    str(projection_intent.request_id),
                    projection_intent.projection_revision,
                    projection_intent.operation_marker,
                    projection_intent.desired_remote_state,
                    projection_intent.expected_remote_state,
                    json.dumps(projection_intent.payload),
                    projection_intent.status.value,
                    projection_intent.attempts,
                    projection_intent.created_at.isoformat(),
                    projection_intent.updated_at.isoformat(),
                    intent_ack,
                    intent_unc,
                    intent_err,
                ),
            )

