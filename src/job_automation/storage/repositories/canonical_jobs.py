"""Canonical jobs, posting revisions, and normalized postings repository."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.storage.connection import transaction
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class CanonicalJobRepository(BaseRepository):
    """Manages C06 NormalizedPosting, C07 CanonicalJob and PostingRevision persistence."""

    def save_canonical_job(self, job: CanonicalJob) -> None:
        """Persist or update a canonical job record and its revisions."""
        now_utc = datetime.now(timezone.utc).isoformat()
        job_json = job.model_dump_json()

        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO canonical_jobs (
                    canonical_job_id, canonical_company_id, company_name,
                    availability, current_revision_id, first_seen_at,
                    last_seen_at, duplicate_proposal_reason, job_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_job_id) DO UPDATE SET
                    canonical_company_id = excluded.canonical_company_id,
                    company_name = excluded.company_name,
                    availability = excluded.availability,
                    current_revision_id = excluded.current_revision_id,
                    last_seen_at = excluded.last_seen_at,
                    duplicate_proposal_reason = excluded.duplicate_proposal_reason,
                    job_json = excluded.job_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(job.canonical_job_id),
                    str(job.canonical_company_id) if job.canonical_company_id else None,
                    job.company_name,
                    job.availability.value,
                    str(job.current_revision_id),
                    job.first_seen_at.isoformat(),
                    job.last_seen_at.isoformat(),
                    job.duplicate_proposal_reason,
                    job_json,
                    now_utc,
                    now_utc,
                ),
            )

            # Persist revisions
            for rev in job.revisions:
                self._save_revision_internal(rev)

            # Sync linked source keys with source_identities if table exists
            try:
                for sk in job.linked_source_keys:
                    self.conn.execute(
                        """
                        INSERT INTO source_identities (
                            provider, board_id, source_posting_id, canonical_job_id,
                            first_seen_at, last_seen_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(provider, board_id, source_posting_id) DO UPDATE SET
                            canonical_job_id = excluded.canonical_job_id,
                            last_seen_at = excluded.last_seen_at,
                            updated_at = excluded.updated_at
                        """,
                        (
                            sk.provider,
                            sk.board_id,
                            sk.source_posting_id,
                            str(job.canonical_job_id),
                            job.first_seen_at.isoformat(),
                            job.last_seen_at.isoformat(),
                            now_utc,
                            now_utc,
                        ),
                    )
            except sqlite3.OperationalError:
                pass

    def _save_revision_internal(self, rev: PostingRevision) -> None:
        """Internal helper to insert or update a posting revision."""
        now_utc = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "SELECT 1 FROM posting_revisions WHERE revision_id = ?",
            (str(rev.revision_id),),
        )
        if cursor.fetchone():
            self.conn.execute(
                """
                UPDATE posting_revisions
                SET canonical_job_id = ?, provider = ?, board_id = ?,
                    source_posting_id = ?, content_hash = ?, title = ?,
                    availability = ?, last_seen_at = ?, revision_json = ?
                WHERE revision_id = ?
                """,
                (
                    str(rev.canonical_job_id),
                    rev.source_key.provider,
                    rev.source_key.board_id,
                    rev.source_key.source_posting_id,
                    rev.content_hash,
                    rev.title,
                    rev.availability.value,
                    rev.last_seen_at.isoformat(),
                    rev.model_dump_json(),
                    str(rev.revision_id),
                ),
            )
            return

        try:
            self.conn.execute(
                """
                INSERT INTO posting_revisions (
                    revision_id, canonical_job_id, provider, board_id,
                    source_posting_id, content_hash, title, availability,
                    first_seen_at, last_seen_at, revision_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_job_id, content_hash) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    availability = excluded.availability,
                    revision_json = excluded.revision_json
                """,
                (
                    str(rev.revision_id),
                    str(rev.canonical_job_id),
                    rev.source_key.provider,
                    rev.source_key.board_id,
                    rev.source_key.source_posting_id,
                    rev.content_hash,
                    rev.title,
                    rev.availability.value,
                    rev.first_seen_at.isoformat(),
                    rev.last_seen_at.isoformat(),
                    rev.model_dump_json(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise DuplicateKeyError(
                    f"Duplicate revision ID '{rev.revision_id}'", constraint="posting_revisions_pk"
                ) from exc
            raise

    def save_revision(self, revision: PostingRevision) -> None:
        """Explicitly save a PostingRevision, rejecting duplicates if revision_id conflicts."""
        try:
            with transaction(self.conn):
                self._save_revision_internal(revision)
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise DuplicateKeyError(
                    f"Revision conflict for revision_id '{revision.revision_id}'",
                    constraint="posting_revisions_unique",
                ) from exc
            raise

    def get_canonical_job(self, canonical_job_id: uuid.UUID) -> CanonicalJob | None:
        """Fetch a canonical job by its UUID."""
        cursor = self.conn.execute(
            "SELECT job_json FROM canonical_jobs WHERE canonical_job_id = ?",
            (str(canonical_job_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return CanonicalJob.model_validate_json(row["job_json"])

    def find_by_source_key(self, source_key: SourceKey) -> CanonicalJob | None:
        """Lookup canonical job by linked source key tuple."""
        try:
            cursor = self.conn.execute(
                """
                SELECT c.job_json
                FROM canonical_jobs c
                JOIN source_identities s ON c.canonical_job_id = s.canonical_job_id
                WHERE s.provider = ? AND s.board_id = ? AND s.source_posting_id = ?
                LIMIT 1
                """,
                (source_key.provider, source_key.board_id, source_key.source_posting_id),
            )
            row = cursor.fetchone()
            if row:
                return CanonicalJob.model_validate_json(row["job_json"])
        except sqlite3.OperationalError:
            pass

        cursor = self.conn.execute(
            """
            SELECT c.job_json
            FROM canonical_jobs c
            JOIN posting_revisions r ON c.canonical_job_id = r.canonical_job_id
            WHERE r.provider = ? AND r.board_id = ? AND r.source_posting_id = ?
            LIMIT 1
            """,
            (source_key.provider, source_key.board_id, source_key.source_posting_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return CanonicalJob.model_validate_json(row["job_json"])

    def get_revisions(self, canonical_job_id: uuid.UUID) -> list[PostingRevision]:
        """Fetch all revisions for a canonical job."""
        cursor = self.conn.execute(
            """
            SELECT revision_json
            FROM posting_revisions
            WHERE canonical_job_id = ?
            ORDER BY first_seen_at ASC
            """,
            (str(canonical_job_id),),
        )
        return [
            PostingRevision.model_validate_json(row["revision_json"])
            for row in cursor.fetchall()
        ]

    def list_jobs(self, availability: PostingAvailability | None = None) -> list[CanonicalJob]:
        """List canonical jobs, optionally filtered by availability."""
        if availability:
            cursor = self.conn.execute(
                "SELECT job_json FROM canonical_jobs WHERE availability = ? ORDER BY last_seen_at DESC",
                (availability.value,),
            )
        else:
            cursor = self.conn.execute(
                "SELECT job_json FROM canonical_jobs ORDER BY last_seen_at DESC"
            )

        return [
            CanonicalJob.model_validate_json(row["job_json"])
            for row in cursor.fetchall()
        ]

    def update_availability(
        self,
        canonical_job_id: uuid.UUID,
        availability: PostingAvailability,
        last_seen_at: datetime | None = None,
    ) -> bool:
        """Narrow atomic availability and last_seen_at update for a CanonicalJob.

        Preserves revisions, company mappings, merge lineage, and all unrelated fields.
        Keeps both SQL availability column and job_json payload in sync.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            cursor = self.conn.execute(
                "SELECT job_json FROM canonical_jobs WHERE canonical_job_id = ?",
                (str(canonical_job_id),),
            )
            row = cursor.fetchone()
            if not row:
                return False
            job = CanonicalJob.model_validate_json(row["job_json"])
            updates: dict[str, Any] = {"availability": availability}
            if last_seen_at is not None:
                updates["last_seen_at"] = last_seen_at
            updated_job = job.model_copy(update=updates)
            updated_json = updated_job.model_dump_json()

            if last_seen_at is not None:
                self.conn.execute(
                    """
                    UPDATE canonical_jobs
                    SET availability = ?, last_seen_at = ?, job_json = ?, updated_at = ?
                    WHERE canonical_job_id = ?
                    """,
                    (
                        availability.value,
                        last_seen_at.isoformat(),
                        updated_json,
                        now_utc,
                        str(canonical_job_id),
                    ),
                )
            else:
                self.conn.execute(
                    """
                    UPDATE canonical_jobs
                    SET availability = ?, job_json = ?, updated_at = ?
                    WHERE canonical_job_id = ?
                    """,
                    (availability.value, updated_json, now_utc, str(canonical_job_id)),
                )
            return True

    def save_normalized_posting(self, normalized: NormalizedPosting) -> None:
        """Persist a C06 NormalizedPosting, enforcing source key uniqueness."""
        now_utc = datetime.now(timezone.utc).isoformat()
        try:
            with transaction(self.conn):
                self.conn.execute(
                    """
                    INSERT INTO normalized_postings (
                        provider, board_id, source_posting_id,
                        raw_reference, raw_content_hash, title, company_name_hint,
                        observed_at, posting_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized.source_key.provider,
                        normalized.source_key.board_id,
                        normalized.source_key.source_posting_id,
                        normalized.raw_reference,
                        normalized.raw_content_hash,
                        normalized.title,
                        normalized.company_name_hint,
                        normalized.observed_at.isoformat(),
                        normalized.model_dump_json(),
                        now_utc,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"Duplicate normalized posting key: ({normalized.source_key.provider}, "
                    f"{normalized.source_key.board_id}, {normalized.source_key.source_posting_id})",
                    constraint="normalized_postings_unique",
                ) from exc
            raise

    def get_normalized_posting(self, source_key: SourceKey) -> NormalizedPosting | None:
        """Fetch normalized posting by source key."""
        cursor = self.conn.execute(
            """
            SELECT posting_json
            FROM normalized_postings
            WHERE provider = ? AND board_id = ? AND source_posting_id = ?
            """,
            (source_key.provider, source_key.board_id, source_key.source_posting_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return NormalizedPosting.model_validate_json(row["posting_json"])
