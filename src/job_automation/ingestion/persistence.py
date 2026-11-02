"""Durable page commit and checkpoint persistence (INGEST-01-S02, S05).

Coordinates atomic commits of page receipts, raw postings, and traversal
checkpoints with StorageEngine.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Sequence

from job_automation.contracts.postings import RawPosting
from job_automation.ingestion.models import PageReceipt, SourceCheckpoint
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class PagePersistenceManager:
    """Manages transactional persistence of page evidence and traversal checkpoints."""

    def __init__(self, storage: StorageEngine) -> None:
        self.storage = storage

    def commit_page(
        self,
        receipt: PageReceipt,
        checkpoint: SourceCheckpoint,
        raw_postings: Sequence[RawPosting],
    ) -> None:
        """Atomically commit a page's raw postings and updated traversal checkpoint."""
        now_utc = datetime.now(timezone.utc).isoformat()
        checkpoint_key = f"{checkpoint.source_key}_{checkpoint.scope_id}"
        checkpoint_id = f"{checkpoint.run_id}_ingestion_{checkpoint_key}"
        checkpoint_json = checkpoint.model_dump_json()

        with self.storage.conn:
            # 1. Persist C05 raw postings within this atomic transaction
            for raw in raw_postings:
                headers_json = json.dumps(raw.raw_headers) if raw.raw_headers else None
                try:
                    self.storage.conn.execute(
                        """
                        INSERT INTO raw_postings (
                            provider, board_id, source_posting_id,
                            raw_payload_ref, raw_content_hash,
                            fetch_time, headers_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            raw.source_key.provider,
                            raw.source_key.board_id,
                            raw.source_key.source_posting_id,
                            raw.raw_payload_ref,
                            raw.raw_content_hash,
                            raw.fetch_time.isoformat(),
                            headers_json,
                            now_utc,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                        # Verify existing posting
                        cur = self.storage.conn.execute(
                            """
                            SELECT raw_content_hash FROM raw_postings
                            WHERE provider = ? AND board_id = ? AND source_posting_id = ?
                            """,
                            (
                                raw.source_key.provider,
                                raw.source_key.board_id,
                                raw.source_key.source_posting_id,
                            ),
                        )
                        row = cur.fetchone()
                        if row and row["raw_content_hash"] == raw.raw_content_hash:
                            # Identical content already preserved
                            continue
                        logger.warning(
                            "Duplicate key '%s' encountered with differing hash '%s' vs '%s'",
                            raw.source_key,
                            raw.raw_content_hash,
                            row["raw_content_hash"] if row else "unknown",
                        )
                        continue
                    raise

            # 2. Persist updated checkpoint in the same transaction
            self.storage.conn.execute(
                """
                INSERT INTO pipeline_checkpoints (
                    checkpoint_id, run_id, stage_name, checkpoint_key,
                    checkpoint_data_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    checkpoint_data_json = excluded.checkpoint_data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    checkpoint_id,
                    str(checkpoint.run_id),
                    "ingestion",
                    checkpoint_key,
                    checkpoint_json,
                    now_utc,
                    now_utc,
                ),
            )

    def load_checkpoint(
        self,
        run_id: uuid.UUID,
        source_key: str,
        scope_id: str,
    ) -> SourceCheckpoint | None:
        """Load stored traversal checkpoint if present."""
        checkpoint_key = f"{source_key}_{scope_id}"
        data = self.storage.runs.get_checkpoint(
            run_id=run_id,
            stage_name="ingestion",
            checkpoint_key=checkpoint_key,
        )
        if data is None:
            return None
        return SourceCheckpoint.model_validate(data)

