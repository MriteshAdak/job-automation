"""Generation request repository and lifecycle recovery."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import GenerationProcessing
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.storage.connection import _TRANSACTION_DEPTHS
from job_automation.storage.exceptions import DuplicateKeyError, RecordNotFoundError
from job_automation.storage.repositories.base import BaseRepository


class GenerationRequestRepository(BaseRepository):
    """Manages C13 GenerationRequest persistence, claiming, and recovery (blueprint §5)."""

    def _execute(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        """Execute a statement safely, respecting outer transactions if active."""
        depth = _TRANSACTION_DEPTHS.get(id(self.conn), 0)
        if depth > 0:
            return self.conn.execute(sql, params)
        with self.conn:
            return self.conn.execute(sql, params)

    def create_request(self, request: GenerationRequest) -> None:
        """Create a new generation request in durable storage.

        Raises DuplicateKeyError on request_id collision.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        frozen_json = (
            request.frozen_input_versions.model_dump_json()
            if request.frozen_input_versions
            else None
        )
        claimed_str = request.claimed_at.isoformat() if request.claimed_at else None
        completed_str = request.completed_at.isoformat() if request.completed_at else None
        err_json = request.error.model_dump_json() if request.error else None

        try:
            self._execute(
                """
                INSERT INTO generation_requests (
                    request_id, salesforce_request_id, client_request_key,
                    canonical_job_id, document_type, target_language,
                    template_id, context_strategy, allow_unavailable_job,
                    state, created_at, claimed_at, completed_at,
                    frozen_inputs_json, predecessor_request_id,
                    result_artifact_ref, error_json, request_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(request.request_id),
                    request.salesforce_request_id,
                    request.client_request_key,
                    str(request.canonical_job_id),
                    request.document_type.value,
                    request.target_language,
                    request.template_id,
                    request.context_strategy.value,
                    1 if request.allow_unavailable_job else 0,
                    request.state.value,
                    request.created_at.isoformat(),
                    claimed_str,
                    completed_str,
                    frozen_json,
                    (
                        str(request.predecessor_request_id)
                        if request.predecessor_request_id
                        else None
                    ),
                    request.result_artifact_ref,
                    err_json,
                    request.model_dump_json(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"GenerationRequest with ID '{request.request_id}' already exists",
                    constraint="generation_requests_pk",
                ) from exc
            raise

    def get_request(self, request_id: uuid.UUID) -> GenerationRequest | None:
        """Fetch generation request by UUID."""
        cursor = self.conn.execute(
            "SELECT request_json FROM generation_requests WHERE request_id = ?",
            (str(request_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return GenerationRequest.model_validate_json(row["request_json"])

    def get_by_salesforce_id(self, salesforce_request_id: str) -> GenerationRequest | None:
        """Fetch generation request by Salesforce record ID."""
        cursor = self.conn.execute(
            "SELECT request_json FROM generation_requests WHERE salesforce_request_id = ? ORDER BY created_at DESC",
            (salesforce_request_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return GenerationRequest.model_validate_json(row["request_json"])

    def get_by_client_key(self, client_key: str) -> GenerationRequest | None:
        """Fetch generation request by idempotent client request key."""
        cursor = self.conn.execute(
            "SELECT request_json FROM generation_requests WHERE client_request_key = ? ORDER BY created_at DESC",
            (client_key,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return GenerationRequest.model_validate_json(row["request_json"])

    def list_by_job(self, canonical_job_id: uuid.UUID) -> list[GenerationRequest]:
        """List all generation requests targeting a canonical job."""
        cursor = self.conn.execute(
            "SELECT request_json FROM generation_requests WHERE canonical_job_id = ? ORDER BY created_at ASC",
            (str(canonical_job_id),),
        )
        return [GenerationRequest.model_validate_json(row["request_json"]) for row in cursor.fetchall()]

    def list_requests_for_job(self, canonical_job_id: uuid.UUID) -> list[GenerationRequest]:
        """Alias for list_by_job."""
        return self.list_by_job(canonical_job_id)

    def update_request(self, request: GenerationRequest) -> None:
        """Update request state, timestamps, frozen inputs, and results."""
        frozen_json = (
            request.frozen_input_versions.model_dump_json()
            if request.frozen_input_versions
            else None
        )
        claimed_str = request.claimed_at.isoformat() if request.claimed_at else None
        completed_str = request.completed_at.isoformat() if request.completed_at else None
        err_json = request.error.model_dump_json() if request.error else None

        self._execute(
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

    def claim_request(
        self,
        request_id: uuid.UUID,
        frozen_inputs: FrozenInputVersions,
    ) -> GenerationRequest:
        """Claim a pending request and freeze its input versions (blueprint §5)."""
        req = self.get_request(request_id)
        if not req:
            raise RecordNotFoundError(f"GenerationRequest '{request_id}' not found")

        claimed_at = datetime.now(timezone.utc)
        updated = req.model_copy(
            update={
                "state": GenerationProcessing.RUNNING,
                "claimed_at": claimed_at,
                "frozen_input_versions": frozen_inputs,
            }
        )
        self.update_request(updated)
        return updated

    def get_unfinished_requests(self) -> list[GenerationRequest]:
        """Fetch all requests in pending, running, or upload_pending state."""
        cursor = self.conn.execute(
            """
            SELECT request_json FROM generation_requests
            WHERE state IN (?, ?, ?)
            ORDER BY created_at ASC
            """,
            (
                GenerationProcessing.PENDING.value,
                GenerationProcessing.RUNNING.value,
                GenerationProcessing.UPLOAD_PENDING.value,
            ),
        )
        return [
            GenerationRequest.model_validate_json(row["request_json"])
            for row in cursor.fetchall()
        ]

    def get_requests_by_states(
        self,
        states: Sequence[GenerationProcessing],
    ) -> list[GenerationRequest]:
        """Fetch all requests matching any of the specified processing states."""
        if not states:
            return []
        placeholders = ",".join("?" for _ in states)
        cursor = self.conn.execute(
            f"""
            SELECT request_json FROM generation_requests
            WHERE state IN ({placeholders})
            ORDER BY created_at ASC
            """,
            tuple(s.value for s in states),
        )
        return [
            GenerationRequest.model_validate_json(row["request_json"])
            for row in cursor.fetchall()
        ]

    def recover_interrupted_requests(
        self,
        reason: str = "Worker process interrupted unexpectedly",
    ) -> int:
        """Mark requests stuck in running or upload_pending as failed with recoverable error."""
        unfinished = self.get_unfinished_requests()
        count = 0
        now_utc = datetime.now(timezone.utc)

        for req in unfinished:
            if req.state in (GenerationProcessing.RUNNING, GenerationProcessing.UPLOAD_PENDING):
                err = ClassifiedError.from_category(
                    category=ErrorCategory.TRANSIENT_SERVICE,
                    message=reason,
                    details={"recovery_state": req.state.value},
                )
                recovered_req = req.model_copy(
                    update={
                        "state": GenerationProcessing.FAILED,
                        "completed_at": now_utc,
                        "error": err,
                    }
                )
                self.update_request(recovered_req)
                count += 1

        return count
