"""Document artifact repository."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from job_automation.contracts.artifacts import Artifact
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class ArtifactRepository(BaseRepository):
    """Manages C14 physical Artifact metadata records in SQLite."""

    def save_artifact(self, artifact: Artifact) -> None:
        """Persist a rendered artifact record.

        Raises DuplicateKeyError on artifact_id collision.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, request_id, artifact_version,
                        format, local_path, content_hash, size_bytes,
                        remote_file_id, delivery_status, approval_status,
                        reconciliation_marker, artifact_json, created_at
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
                        artifact.approval_status.value,
                        artifact.reconciliation_marker,
                        artifact.model_dump_json(),
                        artifact.created_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"Artifact with ID '{artifact.artifact_id}' already exists",
                    constraint="artifacts_pk",
                ) from exc
            raise

    def get_artifact(self, artifact_id: uuid.UUID) -> Artifact | None:
        """Fetch artifact by UUID."""
        cursor = self.conn.execute(
            "SELECT artifact_json FROM artifacts WHERE artifact_id = ?",
            (str(artifact_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Artifact.model_validate_json(row["artifact_json"])

    def list_artifacts_for_request(self, request_id: uuid.UUID) -> list[Artifact]:
        """Fetch all artifacts produced for a given generation request."""
        cursor = self.conn.execute(
            """
            SELECT artifact_json FROM artifacts
            WHERE request_id = ?
            ORDER BY artifact_version ASC
            """,
            (str(request_id),),
        )
        return [
            Artifact.model_validate_json(row["artifact_json"])
            for row in cursor.fetchall()
        ]

    def update_delivery_status(
        self,
        artifact_id: uuid.UUID,
        remote_file_id: str | None,
        delivery_status: str,
    ) -> None:
        """Update remote file ID and delivery status upon Salesforce delivery."""
        art = self.get_artifact(artifact_id)
        if not art:
            return

        updated = art.model_copy(
            update={
                "remote_file_id": remote_file_id or art.remote_file_id,
                "delivery_status": delivery_status,
            }
        )

        with self.conn:
            self.conn.execute(
                """
                UPDATE artifacts
                SET remote_file_id = ?,
                    delivery_status = ?,
                    artifact_json = ?
                WHERE artifact_id = ?
                """,
                (
                    updated.remote_file_id,
                    updated.delivery_status,
                    updated.model_dump_json(),
                    str(artifact_id),
                ),
            )
