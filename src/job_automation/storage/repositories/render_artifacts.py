"""Repository managing render intents, attempts, receipts, and immutable artifact sets (GEN-05-S05)."""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.records import ArtifactDeliveryRecord
from job_automation.generation.render_records import (
    ArtifactSet,
    RenderAttempt,
    RenderIntent,
    RenderedArtifactReceipt,
    canonical_json_dumps,
    compute_file_sha256,
)
from job_automation.storage.connection import transaction
from job_automation.storage.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class RenderArtifactRepository(BaseRepository):
    """Manages persistence, recovery, and atomic publication of rendered physical artifacts."""

    def save_intent(self, intent: RenderIntent) -> RenderIntent:
        """Persist a new render intent or return existing matching intent."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO render_intents (
                    intent_id, request_id, logical_key, spec_hash, artifact_version,
                    target_formats_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(logical_key) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (
                    str(intent.intent_id),
                    str(intent.request_id),
                    intent.logical_key,
                    intent.spec_hash,
                    intent.artifact_version,
                    json.dumps(intent.target_formats),
                    intent.status,
                    intent.created_at.isoformat(),
                    intent.updated_at.isoformat(),
                ),
            )
        return self.get_intent_by_logical_key(intent.logical_key) or intent

    def get_intent_by_request(self, request_id: uuid.UUID) -> RenderIntent | None:
        """Lookup active render intent for a generation request."""
        row = self.conn.execute(
            """
            SELECT * FROM render_intents
            WHERE request_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (str(request_id),),
        ).fetchone()
        if not row:
            return None
        return RenderIntent(
            intent_id=uuid.UUID(row["intent_id"]),
            request_id=uuid.UUID(row["request_id"]),
            logical_key=row["logical_key"],
            spec_hash=row["spec_hash"],
            artifact_version=row["artifact_version"],
            target_formats=json.loads(row["target_formats_json"]),
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_intent_by_logical_key(self, logical_key: str) -> RenderIntent | None:
        """Lookup render intent by its deterministic logical key."""
        row = self.conn.execute(
            "SELECT * FROM render_intents WHERE logical_key = ?",
            (logical_key,),
        ).fetchone()
        if not row:
            return None
        return RenderIntent(
            intent_id=uuid.UUID(row["intent_id"]),
            request_id=uuid.UUID(row["request_id"]),
            logical_key=row["logical_key"],
            spec_hash=row["spec_hash"],
            artifact_version=row["artifact_version"],
            target_formats=json.loads(row["target_formats_json"]),
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_intent_status(self, intent_id: uuid.UUID, status: str) -> None:
        """Update render intent status and updated_at timestamp."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE render_intents SET status = ?, updated_at = ? WHERE intent_id = ?",
                (status, now_utc, str(intent_id)),
            )

    def record_attempt(self, attempt: RenderAttempt) -> None:
        """Record bounded conversion attempt audit row."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO render_attempts (
                    attempt_id, intent_id, request_id, attempt_number, format,
                    staging_dir, started_at, completed_at, status, exit_code,
                    duration_ms, error_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(attempt.attempt_id),
                    str(attempt.intent_id),
                    str(attempt.request_id),
                    attempt.attempt_number,
                    attempt.format,
                    attempt.staging_dir,
                    attempt.started_at.isoformat(),
                    attempt.completed_at.isoformat() if attempt.completed_at else None,
                    attempt.status,
                    attempt.exit_code,
                    attempt.duration_ms,
                    json.dumps(attempt.error_json) if attempt.error_json else None,
                ),
            )

    def list_attempts_for_intent(self, intent_id: uuid.UUID) -> list[RenderAttempt]:
        """List all logged attempts for a given render intent ordered by attempt number."""
        rows = self.conn.execute(
            """
            SELECT * FROM render_attempts
            WHERE intent_id = ?
            ORDER BY attempt_number ASC
            """,
            (str(intent_id),),
        ).fetchall()
        attempts: list[RenderAttempt] = []
        for r in rows:
            attempts.append(
                RenderAttempt(
                    attempt_id=uuid.UUID(r["attempt_id"]),
                    intent_id=uuid.UUID(r["intent_id"]),
                    request_id=uuid.UUID(r["request_id"]),
                    attempt_number=r["attempt_number"],
                    format=r["format"],
                    staging_dir=r["staging_dir"],
                    started_at=datetime.fromisoformat(r["started_at"]),
                    completed_at=datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
                    status=r["status"],
                    exit_code=r["exit_code"],
                    duration_ms=r["duration_ms"],
                    error_json=json.loads(r["error_json"]) if r["error_json"] else None,
                )
            )
        return attempts

    def save_receipt_and_artifact(
        self,
        receipt: RenderedArtifactReceipt,
        artifact: Artifact,
        delivery_slot: ArtifactDeliveryRecord,
    ) -> None:
        """Atomically persist rendered format receipt, C14 Artifact row, and delivery slot."""
        with transaction(self.conn):
            # 1. Insert rendered artifact receipt
            self.conn.execute(
                """
                INSERT INTO rendered_artifact_receipts (
                    receipt_id, request_id, artifact_id, artifact_set_id, format,
                    version, content_hash, size_bytes, local_path, relative_managed_path,
                    spec_hash, draft_hash, report_hash, layout_digest,
                    docx_artifact_id, docx_content_hash, output_checks_json,
                    created_at, receipt_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, version, format) DO UPDATE SET
                    artifact_id = excluded.artifact_id,
                    content_hash = excluded.content_hash,
                    size_bytes = excluded.size_bytes,
                    local_path = excluded.local_path,
                    receipt_hash = excluded.receipt_hash
                """,
                (
                    str(receipt.receipt_id),
                    str(receipt.request_id),
                    str(receipt.artifact_id),
                    str(receipt.artifact_set_id),
                    receipt.format,
                    receipt.version,
                    receipt.content_hash,
                    receipt.size_bytes,
                    receipt.local_path,
                    receipt.relative_managed_path,
                    receipt.spec_hash,
                    receipt.draft_hash,
                    receipt.report_hash,
                    receipt.layout_digest,
                    str(receipt.docx_artifact_id) if receipt.docx_artifact_id else None,
                    receipt.docx_content_hash,
                    json.dumps(receipt.output_checks),
                    receipt.created_at.isoformat(),
                    receipt.receipt_hash,
                ),
            )

            # 2. Insert or replace C14 Artifact metadata row
            self.conn.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                    artifact_id, request_id, artifact_version, format, local_path,
                    content_hash, size_bytes, remote_file_id, delivery_status,
                    approval_status, reconciliation_marker, created_at, artifact_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(artifact.artifact_id),
                    str(artifact.request_id),
                    artifact.artifact_version,
                    artifact.format,
                    artifact.local_path,
                    artifact.content_hash,
                    artifact.size_bytes,
                    artifact.remote_file_id,
                    artifact.delivery_status,
                    artifact.approval_status.value if hasattr(artifact.approval_status, "value") else str(artifact.approval_status),
                    artifact.reconciliation_marker,
                    artifact.created_at.isoformat(),
                    artifact.model_dump_json(),
                ),
            )

            # 3. Update or replace active generation delivery slot pointer
            self.conn.execute(
                """
                INSERT INTO generation_artifact_deliveries (
                    delivery_id, request_id, artifact_format, artifact_id, artifact_hash,
                    remote_file_id, delivery_status, delivered_at, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, artifact_format) DO UPDATE SET
                    artifact_id = excluded.artifact_id,
                    artifact_hash = excluded.artifact_hash,
                    delivery_status = excluded.delivery_status
                """,
                (
                    str(uuid.uuid4()),
                    str(delivery_slot.request_id),
                    delivery_slot.artifact_format,
                    str(delivery_slot.artifact_id),
                    delivery_slot.artifact_hash,
                    delivery_slot.remote_file_id,
                    delivery_slot.delivery_status,
                    delivery_slot.delivered_at.isoformat() if delivery_slot.delivered_at else None,
                    json.dumps(delivery_slot.receipt_data),
                ),
            )

    def commit_artifact_set(self, artifact_set: ArtifactSet) -> None:
        """Persist or update the completed ArtifactSet record."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO artifact_sets (
                    set_id, request_id, set_version, required_formats_json,
                    is_complete, report_id, report_hash, draft_hash,
                    set_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, set_version) DO UPDATE SET
                    is_complete = excluded.is_complete,
                    set_hash = excluded.set_hash
                """,
                (
                    str(artifact_set.set_id),
                    str(artifact_set.request_id),
                    artifact_set.set_version,
                    json.dumps(artifact_set.required_formats),
                    1 if artifact_set.is_complete else 0,
                    str(artifact_set.report_id),
                    artifact_set.report_hash,
                    artifact_set.draft_hash,
                    artifact_set.set_hash,
                    artifact_set.created_at.isoformat(),
                ),
            )

    def get_receipts_by_request(
        self,
        request_id: uuid.UUID,
        version: int = 1,
    ) -> list[RenderedArtifactReceipt]:
        """Fetch all rendered artifact receipts for a request and version."""
        rows = self.conn.execute(
            """
            SELECT * FROM rendered_artifact_receipts
            WHERE request_id = ? AND version = ?
            ORDER BY created_at ASC
            """,
            (str(request_id), version),
        ).fetchall()

        receipts: list[RenderedArtifactReceipt] = []
        for r in rows:
            receipts.append(
                RenderedArtifactReceipt(
                    receipt_id=uuid.UUID(r["receipt_id"]),
                    request_id=uuid.UUID(r["request_id"]),
                    artifact_id=uuid.UUID(r["artifact_id"]),
                    artifact_set_id=uuid.UUID(r["artifact_set_id"]),
                    format=r["format"],
                    version=r["version"],
                    content_hash=r["content_hash"],
                    size_bytes=r["size_bytes"],
                    local_path=r["local_path"],
                    relative_managed_path=r["relative_managed_path"],
                    spec_hash=r["spec_hash"],
                    draft_hash=r["draft_hash"],
                    report_hash=r["report_hash"],
                    layout_digest=r["layout_digest"],
                    docx_artifact_id=uuid.UUID(r["docx_artifact_id"]) if r["docx_artifact_id"] else None,
                    docx_content_hash=r["docx_content_hash"],
                    output_checks=json.loads(r["output_checks_json"]),
                    created_at=datetime.fromisoformat(r["created_at"]),
                    receipt_hash=r["receipt_hash"],
                )
            )
        return receipts

    def get_artifact_set(
        self,
        request_id: uuid.UUID,
        version: int = 1,
    ) -> ArtifactSet | None:
        """Fetch ArtifactSet record for a request and version."""
        row = self.conn.execute(
            """
            SELECT * FROM artifact_sets
            WHERE request_id = ? AND set_version = ?
            """,
            (str(request_id), version),
        ).fetchone()
        if not row:
            return None

        receipts = self.get_receipts_by_request(request_id, version)
        artifacts_map = {rcpt.format: rcpt for rcpt in receipts}

        return ArtifactSet(
            set_id=uuid.UUID(row["set_id"]),
            request_id=uuid.UUID(row["request_id"]),
            set_version=row["set_version"],
            required_formats=json.loads(row["required_formats_json"]),
            artifacts=artifacts_map,
            is_complete=bool(row["is_complete"]),
            report_id=uuid.UUID(row["report_id"]),
            report_hash=row["report_hash"],
            draft_hash=row["draft_hash"],
            set_hash=row["set_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def reopen_and_verify_set(
        self,
        request_id: uuid.UUID,
        version: int = 1,
    ) -> tuple[ArtifactSet | None, ClassifiedError | None]:
        """Reopen a saved ArtifactSet and verify physical file presence, size, and SHA-256 on disk."""
        artifact_set = self.get_artifact_set(request_id, version)
        if artifact_set is None:
            return None, None

        if not artifact_set.is_complete:
            return None, None

        for fmt in artifact_set.required_formats:
            rcpt = artifact_set.artifacts.get(fmt)
            if rcpt is None:
                return None, ClassifiedError.validation(f"Missing receipt for required format '{fmt}'")

            file_path = Path(rcpt.local_path)
            if not file_path.is_file():
                return None, ClassifiedError.validation(
                    f"Physical artifact file missing on disk: {rcpt.local_path}"
                )

            # Exact size check
            stat_size = file_path.stat().st_size
            if stat_size != rcpt.size_bytes:
                return None, ClassifiedError.validation(
                    f"Physical artifact size mismatch for {rcpt.local_path}: "
                    f"expected {rcpt.size_bytes}, found {stat_size}"
                )

            # Exact byte hash check
            computed_hash = compute_file_sha256(file_path)
            if computed_hash != rcpt.content_hash:
                return None, ClassifiedError.validation(
                    f"Physical artifact byte hash mismatch for {rcpt.local_path}: "
                    f"expected {rcpt.content_hash}, computed {computed_hash}"
                )

        return artifact_set, None
