"""Raw posting and fetch manifest repository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.postings import FetchManifest, RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.filestore import Filestore
from job_automation.storage.repositories.base import BaseRepository


class RawPostingRepository(BaseRepository):
    """Manages C05 RawPosting persistence and C04 FetchManifests.

    Enforces uniqueness constraint on (provider, board_id, source_posting_id)
    (blueprint §5).
    """

    def __init__(self, conn: sqlite3.Connection, filestore: Filestore | None = None) -> None:
        super().__init__(conn)
        self.filestore = filestore

    def save_raw_posting(self, raw: RawPosting) -> None:
        """Persist a raw posting record.

        Enforces uniqueness on (provider, board_id, source_posting_id).
        Raises DuplicateKeyError on unique constraint violation.
        """
        provider = raw.source_key.provider
        board_id = raw.source_key.board_id
        source_posting_id = raw.source_key.source_posting_id
        now_utc = datetime.now(timezone.utc).isoformat()
        headers_json = json.dumps(raw.raw_headers) if raw.raw_headers else None

        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO raw_postings (
                        provider, board_id, source_posting_id,
                        raw_payload_ref, raw_content_hash,
                        fetch_time, headers_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provider,
                        board_id,
                        source_posting_id,
                        raw.raw_payload_ref,
                        raw.raw_content_hash,
                        raw.fetch_time.isoformat(),
                        headers_json,
                        now_utc,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"Duplicate source posting key: ({provider}, {board_id}, {source_posting_id})",
                    constraint="raw_postings_pk",
                ) from exc
            raise

    def get_raw_posting(self, source_key: SourceKey) -> RawPosting | None:
        """Fetch raw posting by SourceKey, loading payload text from ref."""
        cursor = self.conn.execute(
            """
            SELECT provider, board_id, source_posting_id, raw_payload_ref,
                   raw_content_hash, fetch_time, headers_json
            FROM raw_postings
            WHERE provider = ? AND board_id = ? AND source_posting_id = ?
            """,
            (source_key.provider, source_key.board_id, source_key.source_posting_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        # Resolve payload content from disk reference
        payload_text = ""
        try:
            if self.filestore:
                payload_text = self.filestore.read_raw_payload(row["raw_payload_ref"])
            else:
                p = Path(row["raw_payload_ref"])
                if p.is_file():
                    payload_text = p.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            payload_text = ""

        headers = json.loads(row["headers_json"]) if row["headers_json"] else None

        return RawPosting(
            raw_payload_ref=row["raw_payload_ref"],
            raw_content_hash=row["raw_content_hash"],
            source_key=source_key,
            fetch_time=datetime.fromisoformat(row["fetch_time"]),
            raw_headers=headers,
            raw_payload=payload_text,
        )

    def save_manifest(self, manifest: FetchManifest) -> None:
        """Persist a C04 FetchManifest."""
        now_utc = datetime.now(timezone.utc).isoformat()
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO fetch_manifests (
                        manifest_id, run_id, source_key, scope_id,
                        start_time, end_time, outcome, manifest_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        str(manifest.run_id),
                        manifest.source_key,
                        manifest.scope_id,
                        manifest.start_time.isoformat(),
                        manifest.end_time.isoformat(),
                        manifest.outcome.value,
                        manifest.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise

    def get_manifests_for_run(self, run_id: uuid.UUID) -> list[FetchManifest]:
        """Fetch all manifests recorded for a given run ID."""
        cursor = self.conn.execute(
            "SELECT manifest_json FROM fetch_manifests WHERE run_id = ?",
            (str(run_id),),
        )
        return [
            FetchManifest.model_validate_json(row["manifest_json"])
            for row in cursor.fetchall()
        ]
