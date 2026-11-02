"""Durable repository for candidate-owned field snapshots and backup checkpoints."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.salesforce.sync_records import CandidateFieldSnapshot
from job_automation.storage.repositories.base import BaseRepository


class CandidateSnapshotRepository(BaseRepository):
    """Manages candidate-owned field snapshots (read from Salesforce) and backup checkpoints."""

    def save_snapshot(self, snapshot: CandidateFieldSnapshot) -> None:
        """Persist a candidate field snapshot."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO candidate_snapshots (
                    snapshot_id, org_id, canonical_job_id, remote_record_id,
                    mapping_version, snapshot_hash, candidate_fields_json,
                    source_modification_token, observed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(snapshot.snapshot_id),
                    snapshot.org_id,
                    str(snapshot.canonical_job_id),
                    snapshot.remote_record_id,
                    snapshot.mapping_version,
                    snapshot.snapshot_hash,
                    json.dumps(snapshot.candidate_fields),
                    snapshot.source_modification_token,
                    snapshot.observed_at.isoformat(),
                    now_utc,
                ),
            )

    def get_latest_snapshot(
        self, canonical_job_id: uuid.UUID
    ) -> CandidateFieldSnapshot | None:
        """Fetch the most recent candidate field snapshot for a job."""
        cursor = self.conn.execute(
            """
            SELECT snapshot_id, org_id, canonical_job_id, remote_record_id,
                   mapping_version, snapshot_hash, candidate_fields_json,
                   source_modification_token, observed_at, created_at
            FROM candidate_snapshots
            WHERE canonical_job_id = ?
            ORDER BY observed_at DESC LIMIT 1
            """,
            (str(canonical_job_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_snapshot(row)

    def get_snapshots_for_job(
        self, canonical_job_id: uuid.UUID
    ) -> list[CandidateFieldSnapshot]:
        """Fetch all candidate snapshots for a job in chronological order."""
        cursor = self.conn.execute(
            """
            SELECT snapshot_id, org_id, canonical_job_id, remote_record_id,
                   mapping_version, snapshot_hash, candidate_fields_json,
                   source_modification_token, observed_at, created_at
            FROM candidate_snapshots
            WHERE canonical_job_id = ?
            ORDER BY observed_at ASC
            """,
            (str(canonical_job_id),),
        )
        return [self._row_to_snapshot(r) for r in cursor.fetchall()]

    def save_checkpoint(
        self,
        checkpoint_id: str,
        org_id: str,
        last_processed_key: str | None,
        is_complete: bool,
        records_processed: int,
    ) -> None:
        """Save candidate field backup checkpoint."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO candidate_backup_checkpoints (
                    checkpoint_id, org_id, last_processed_key, is_complete,
                    records_processed, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    last_processed_key = excluded.last_processed_key,
                    is_complete = excluded.is_complete,
                    records_processed = excluded.records_processed,
                    completed_at = CASE WHEN excluded.is_complete = 1 THEN ? ELSE completed_at END
                """,
                (
                    checkpoint_id,
                    org_id,
                    last_processed_key,
                    1 if is_complete else 0,
                    records_processed,
                    now_utc,
                    now_utc if is_complete else None,
                    now_utc,
                ),
            )

    def get_latest_checkpoint(self, org_id: str) -> dict[str, Any] | None:
        """Get the latest backup checkpoint for an org."""
        cursor = self.conn.execute(
            """
            SELECT checkpoint_id, org_id, last_processed_key, is_complete,
                   records_processed, started_at, completed_at
            FROM candidate_backup_checkpoints
            WHERE org_id = ?
            ORDER BY started_at DESC LIMIT 1
            """,
            (org_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def _row_to_snapshot(self, r: sqlite3.Row) -> CandidateFieldSnapshot:
        fields = json.loads(r["candidate_fields_json"])
        return CandidateFieldSnapshot(
            snapshot_id=uuid.UUID(r["snapshot_id"]),
            org_id=r["org_id"],
            canonical_job_id=uuid.UUID(r["canonical_job_id"]),
            remote_record_id=r["remote_record_id"],
            mapping_version=r["mapping_version"],
            snapshot_hash=r["snapshot_hash"],
            candidate_fields=fields,
            source_modification_token=r["source_modification_token"],
            observed_at=datetime.fromisoformat(r["observed_at"]),
            created_at=datetime.fromisoformat(r["created_at"]),
        )

