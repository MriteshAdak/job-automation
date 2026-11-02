"""SQLite repository for local retrieval index generations, activations, builds, and pins."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_automation.contracts.retrieval_index import (
    IndexBuildRecord,
    IndexManifest,
)
from job_automation.storage.connection import transaction
from job_automation.storage.exceptions import DuplicateKeyError, StorageError
from job_automation.storage.repositories.base import BaseRepository


class ContextIndexRepository(BaseRepository):
    """Manages persistence and status transitions for index generations and activations."""

    def save_generation(
        self,
        manifest: IndexManifest,
        generation_dir: Path | str,
        status: str = "ready",
    ) -> None:
        """Insert a newly staged or ready index generation."""
        now_utc = datetime.now(timezone.utc).isoformat()
        manifest_json = manifest.model_dump_json()

        try:
            with transaction(self.conn):
                self.conn.execute(
                    """
                    INSERT INTO context_index_generations (
                        generation_id, candidate_id, profile_version, purpose,
                        snapshot_fingerprint, chunk_manifest_hash, embedding_space_fingerprint,
                        settings_fingerprint, logical_build_fingerprint, artifact_fingerprint,
                        status, row_count, dimension, generation_dir, manifest_json,
                        created_at, finalized_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(manifest.generation_id),
                        str(manifest.candidate_id),
                        manifest.profile_version,
                        manifest.purpose,
                        manifest.snapshot_fingerprint,
                        manifest.chunk_manifest_hash,
                        manifest.embedding_space_fingerprint,
                        manifest.settings_fingerprint,
                        manifest.logical_build_fingerprint,
                        manifest.artifact_fingerprint,
                        status,
                        manifest.row_count,
                        manifest.dimension,
                        str(generation_dir),
                        manifest_json,
                        now_utc,
                        now_utc if status in ("ready", "active") else None,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper() or "PRIMARY KEY" in str(exc).upper():
                raise DuplicateKeyError(
                    f"Context index generation '{manifest.generation_id}' already exists: {exc}"
                ) from exc
            raise StorageError(f"Failed to save context index generation: {exc}") from exc

    def get_generation(self, generation_id: uuid.UUID) -> dict[str, Any] | None:
        """Retrieve index generation row by generation_id."""
        cursor = self.conn.execute(
            """
            SELECT generation_id, candidate_id, profile_version, purpose,
                   snapshot_fingerprint, chunk_manifest_hash, embedding_space_fingerprint,
                   settings_fingerprint, logical_build_fingerprint, artifact_fingerprint,
                   status, row_count, dimension, generation_dir, manifest_json,
                   created_at, finalized_at
            FROM context_index_generations
            WHERE generation_id = ?
            """,
            (str(generation_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def update_generation_status(
        self,
        generation_id: uuid.UUID,
        status: str,
        finalized_at: str | None = None,
    ) -> None:
        """Update lifecycle status of an index generation."""
        with transaction(self.conn):
            if finalized_at is not None:
                self.conn.execute(
                    """
                    UPDATE context_index_generations
                    SET status = ?, finalized_at = ?
                    WHERE generation_id = ?
                    """,
                    (status, finalized_at, str(generation_id)),
                )
            else:
                self.conn.execute(
                    """
                    UPDATE context_index_generations
                    SET status = ?
                    WHERE generation_id = ?
                    """,
                    (status, str(generation_id)),
                )

    def save_build_record(self, record: IndexBuildRecord) -> None:
        """Persist a build execution ledger record."""
        record_json = record.model_dump_json()
        error_json = record.error.model_dump_json() if record.error else None
        call_ids_json = json.dumps([str(cid) for cid in record.embedding_call_ids])

        try:
            with transaction(self.conn):
                self.conn.execute(
                    """
                    INSERT INTO context_index_build_records (
                        build_id, generation_id, candidate_id, profile_version, purpose,
                        status, started_at, completed_at, duration_ms, chunk_count,
                        call_count, call_ids_json, error_json, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(record.build_id),
                        str(record.generation_id),
                        str(record.candidate_id),
                        record.profile_version,
                        record.purpose,
                        record.status,
                        record.started_at.isoformat(),
                        record.completed_at.isoformat(),
                        record.duration_ms,
                        record.chunk_count,
                        len(record.embedding_call_ids),
                        call_ids_json,
                        error_json,
                        record_json,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateKeyError(f"Build record '{record.build_id}' already exists: {exc}") from exc

    def get_build_record(self, build_id: uuid.UUID) -> IndexBuildRecord | None:
        """Retrieve an IndexBuildRecord by build_id."""
        cursor = self.conn.execute(
            "SELECT record_json FROM context_index_build_records WHERE build_id = ?",
            (str(build_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return IndexBuildRecord.model_validate_json(row["record_json"])

    def get_active_generation(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
    ) -> dict[str, Any] | None:
        """Fetch active generation metadata and manifest for candidate and purpose."""
        cursor = self.conn.execute(
            """
            SELECT a.candidate_id, a.purpose, a.active_generation_id, a.profile_version,
                   a.activation_token, a.activated_at,
                   g.snapshot_fingerprint, g.chunk_manifest_hash, g.embedding_space_fingerprint,
                   g.settings_fingerprint, g.logical_build_fingerprint, g.artifact_fingerprint,
                   g.status, g.row_count, g.dimension, g.generation_dir, g.manifest_json,
                   g.created_at, g.finalized_at
            FROM context_index_activations a
            JOIN context_index_generations g ON a.active_generation_id = g.generation_id
            WHERE a.candidate_id = ? AND a.purpose = ?
            """,
            (str(candidate_id), purpose),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def set_active_generation(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
        generation_id: uuid.UUID,
        profile_version: str,
        activation_token: str,
        expected_prior_token: str | None = None,
    ) -> None:
        """Transactionally activate an index generation using compare-and-swap semantics."""
        with transaction(self.conn):
            # 1. Check existing activation
            cursor = self.conn.execute(
                "SELECT active_generation_id, activation_token FROM context_index_activations WHERE candidate_id = ? AND purpose = ?",
                (str(candidate_id), purpose),
            )
            existing = cursor.fetchone()

            if existing is not None:
                current_token = existing["activation_token"]
                old_generation_id = existing["active_generation_id"]
                if expected_prior_token is not None and expected_prior_token != current_token:
                    raise StorageError(
                        f"Activation token conflict: expected '{expected_prior_token}', found '{current_token}'"
                    )

                # Retire old active generation
                self.conn.execute(
                    "UPDATE context_index_generations SET status = 'retired' WHERE generation_id = ?",
                    (old_generation_id,),
                )

            # 2. Update target generation to active
            now_utc = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                "UPDATE context_index_generations SET status = 'active', finalized_at = ? WHERE generation_id = ?",
                (now_utc, str(generation_id)),
            )

            # 3. Insert or replace activation pointer
            self.conn.execute(
                """
                INSERT OR REPLACE INTO context_index_activations (
                    candidate_id, purpose, active_generation_id, profile_version,
                    activation_token, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(candidate_id),
                    purpose,
                    str(generation_id),
                    profile_version,
                    activation_token,
                    now_utc,
                ),
            )

    def list_generations(
        self,
        candidate_id: uuid.UUID,
        purpose: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List generation records matching candidate and optional filters."""
        query = (
            "SELECT generation_id, candidate_id, profile_version, purpose, status, "
            "row_count, dimension, generation_dir, manifest_json, created_at, finalized_at "
            "FROM context_index_generations WHERE candidate_id = ?"
        )
        params: list[Any] = [str(candidate_id)]

        if purpose is not None:
            query += " AND purpose = ?"
            params.append(purpose)
        if status is not None:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"
        cursor = self.conn.execute(query, tuple(params))
        return [dict(r) for r in cursor.fetchall()]

    def pin_generation(
        self,
        generation_id: uuid.UUID,
        pinned_for: str,
        pinned_by: str,
    ) -> uuid.UUID:
        """Create an active pin on an index generation."""
        pin_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO context_index_pins (pin_id, generation_id, pinned_for, pinned_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(pin_id), str(generation_id), pinned_for, pinned_by, now_utc),
            )
        return pin_id

    def release_pin(self, pin_id: uuid.UUID) -> None:
        """Release an existing pin."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE context_index_pins SET released_at = ? WHERE pin_id = ? AND released_at IS NULL",
                (now_utc, str(pin_id)),
            )

    def is_generation_pinned(self, generation_id: uuid.UUID) -> bool:
        """Return True if generation has any active (unreleased) pins."""
        cursor = self.conn.execute(
            "SELECT 1 FROM context_index_pins WHERE generation_id = ? AND released_at IS NULL LIMIT 1",
            (str(generation_id),),
        )
        return cursor.fetchone() is not None
