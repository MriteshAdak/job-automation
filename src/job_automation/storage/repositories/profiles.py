"""Repository for candidate profiles, drafts, provenance, and immutable snapshots.

Enforces:
- Insert-only immutable published profile snapshots.
- Preservation of historical facts for exact C08 resolution.
- Atomic publication and current-version pointer management.
- Unapproved draft persistence and retrieval.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from job_automation.contracts.profile import CandidateFact, ProfileSnapshot
from job_automation.profile.models import (
    DraftProfile,
    ProfileVersionRecord,
    ProvenanceRecord,
)
from job_automation.storage.connection import transaction
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class ProfileRepository(BaseRepository):
    """Persistence operations for profile drafts, provenance, and immutable snapshots."""

    # -----------------------------------------------------------------------
    # Drafts
    # -----------------------------------------------------------------------

    def save_draft(self, draft: DraftProfile) -> None:
        """Persist or update an unapproved profile draft."""
        draft_json = draft.model_dump_json()
        now_utc = datetime.now(timezone.utc).isoformat()

        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO profile_drafts (
                    draft_id, candidate_id, base_profile_version, content_digest,
                    draft_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    base_profile_version = excluded.base_profile_version,
                    content_digest = excluded.content_digest,
                    draft_json = excluded.draft_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(draft.draft_id),
                    str(draft.candidate_id),
                    draft.base_profile_version,
                    draft.content_digest,
                    draft_json,
                    draft.created_at.isoformat(),
                    now_utc,
                ),
            )

    def get_draft(self, draft_id: uuid.UUID) -> DraftProfile | None:
        """Retrieve an unapproved draft by UUID."""
        cursor = self.conn.execute(
            "SELECT draft_json FROM profile_drafts WHERE draft_id = ?",
            (str(draft_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return DraftProfile.model_validate_json(row["draft_json"])

    def list_drafts(self, candidate_id: uuid.UUID | None = None) -> list[DraftProfile]:
        """List all unapproved drafts, optionally filtered by candidate."""
        if candidate_id is not None:
            cursor = self.conn.execute(
                "SELECT draft_json FROM profile_drafts WHERE candidate_id = ? ORDER BY created_at DESC",
                (str(candidate_id),),
            )
        else:
            cursor = self.conn.execute(
                "SELECT draft_json FROM profile_drafts ORDER BY created_at DESC"
            )
        return [DraftProfile.model_validate_json(row["draft_json"]) for row in cursor.fetchall()]

    def delete_draft(self, draft_id: uuid.UUID) -> bool:
        """Delete an unapproved draft."""
        with transaction(self.conn):
            cursor = self.conn.execute(
                "DELETE FROM profile_drafts WHERE draft_id = ?",
                (str(draft_id),),
            )
            return cursor.rowcount > 0

    # -----------------------------------------------------------------------
    # Provenance
    # -----------------------------------------------------------------------

    def save_provenance(self, record: ProvenanceRecord) -> None:
        """Persist candidate evidence provenance metadata."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO profile_provenance (
                    provenance_id, candidate_id, source_type, locator,
                    content_hash, file_path, captured_at, notes, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provenance_id) DO UPDATE SET
                    source_type = excluded.source_type,
                    locator = excluded.locator,
                    content_hash = excluded.content_hash,
                    file_path = excluded.file_path,
                    notes = excluded.notes,
                    metadata_json = excluded.metadata_json
                """,
                (
                    record.provenance_id,
                    str(record.candidate_id),
                    record.source_type,
                    record.locator,
                    record.content_hash,
                    record.file_path,
                    record.captured_at.isoformat(),
                    record.notes,
                    record.model_dump_json(),
                ),
            )

    def get_provenance(self, provenance_id: str) -> ProvenanceRecord | None:
        """Retrieve provenance metadata by identifier."""
        cursor = self.conn.execute(
            "SELECT metadata_json FROM profile_provenance WHERE provenance_id = ?",
            (provenance_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ProvenanceRecord.model_validate_json(row["metadata_json"])

    def list_provenance(self, candidate_id: uuid.UUID) -> list[ProvenanceRecord]:
        """List all provenance records for a candidate."""
        cursor = self.conn.execute(
            "SELECT metadata_json FROM profile_provenance WHERE candidate_id = ? ORDER BY captured_at ASC",
            (str(candidate_id),),
        )
        return [ProvenanceRecord.model_validate_json(row["metadata_json"]) for row in cursor.fetchall()]

    # -----------------------------------------------------------------------
    # Published Snapshots and Facts
    # -----------------------------------------------------------------------

    def publish_snapshot(
        self,
        snapshot: ProfileSnapshot,
        version_sequence: int,
        predecessor_version: str | None,
        content_hash: str,
        approved_by: str,
        approved_at: datetime,
        notes: str | None = None,
        is_current: bool = True,
    ) -> None:
        """Publish an approved C01 snapshot immutably."""
        version = snapshot.profile_version
        candidate_id_str = str(snapshot.candidate_id)

        # Check immutability: if version already exists
        cursor = self.conn.execute(
            "SELECT content_hash FROM profiles WHERE profile_version = ?",
            (version,),
        )
        existing = cursor.fetchone()
        if existing:
            if existing["content_hash"] == content_hash:
                # Idempotent re-publication
                return
            raise DuplicateKeyError(
                f"Profile version '{version}' already published with different content hash"
            )

        now_utc = datetime.now(timezone.utc).isoformat()
        snapshot_json = snapshot.model_dump_json()

        with transaction(self.conn):
            # Insert profiles row
            self.conn.execute(
                """
                INSERT INTO profiles (
                    candidate_id, profile_version, version_sequence, predecessor_version,
                    is_current, approved_by, approved_at, notes, content_hash,
                    snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id_str,
                    version,
                    version_sequence,
                    predecessor_version,
                    1 if is_current else 0,
                    approved_by,
                    approved_at.isoformat(),
                    notes,
                    content_hash,
                    snapshot_json,
                    now_utc,
                ),
            )

            # Insert facts into profile_facts
            for fact in snapshot.evidence_records:
                self.conn.execute(
                    """
                    INSERT INTO profile_facts (
                        profile_version, fact_id, parent_id, kind, title,
                        allowed_uses_json, provenance, fact_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version,
                        str(fact.fact_id),
                        str(fact.parent_id) if fact.parent_id else None,
                        fact.kind.value,
                        fact.title,
                        json.dumps(fact.allowed_uses),
                        fact.provenance,
                        fact.model_dump_json(),
                    ),
                )

            # Update current pointer if requested
            if is_current:
                self.conn.execute(
                    """
                    INSERT INTO profile_current (candidate_id, current_version, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                        current_version = excluded.current_version,
                        updated_at = excluded.updated_at
                    """,
                    (candidate_id_str, version, now_utc),
                )
                # Demote any previously marked current versions for this candidate
                self.conn.execute(
                    "UPDATE profiles SET is_current = 0 WHERE candidate_id = ? AND profile_version != ?",
                    (candidate_id_str, version),
                )
                self.conn.execute(
                    "UPDATE profiles SET is_current = 1 WHERE profile_version = ?",
                    (version,),
                )

    def get_snapshot(self, profile_version: str) -> ProfileSnapshot | None:
        """Retrieve an approved C01 ProfileSnapshot by version."""
        cursor = self.conn.execute(
            "SELECT snapshot_json FROM profiles WHERE profile_version = ?",
            (profile_version,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ProfileSnapshot.model_validate_json(row["snapshot_json"])

    def get_current_version(self, candidate_id: uuid.UUID | None = None) -> str | None:
        """Return version string of the current profile snapshot."""
        if candidate_id is not None:
            cursor = self.conn.execute(
                "SELECT current_version FROM profile_current WHERE candidate_id = ?",
                (str(candidate_id),),
            )
        else:
            cursor = self.conn.execute(
                "SELECT current_version FROM profile_current LIMIT 1"
            )
        row = cursor.fetchone()
        return str(row["current_version"]) if row else None

    def get_current_snapshot(self, candidate_id: uuid.UUID | None = None) -> ProfileSnapshot | None:
        """Retrieve current approved C01 snapshot."""
        current_ver = self.get_current_version(candidate_id)
        if not current_ver:
            return None
        return self.get_snapshot(current_ver)

    def get_version_history(self, candidate_id: uuid.UUID | None = None) -> list[ProfileVersionRecord]:
        """Return ordered list of published version records."""
        if candidate_id is not None:
            cursor = self.conn.execute(
                """
                SELECT profile_version, candidate_id, version_sequence, predecessor_version,
                       is_current, approved_by, approved_at, notes, content_hash, created_at
                FROM profiles WHERE candidate_id = ? ORDER BY version_sequence ASC
                """,
                (str(candidate_id),),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT profile_version, candidate_id, version_sequence, predecessor_version,
                       is_current, approved_by, approved_at, notes, content_hash, created_at
                FROM profiles ORDER BY version_sequence ASC
                """
            )
        records: list[ProfileVersionRecord] = []
        for row in cursor.fetchall():
            records.append(
                ProfileVersionRecord(
                    profile_version=row["profile_version"],
                    candidate_id=uuid.UUID(row["candidate_id"]),
                    version_sequence=row["version_sequence"],
                    predecessor_version=row["predecessor_version"],
                    is_current=bool(row["is_current"]),
                    approved_by=row["approved_by"],
                    approved_at=datetime.fromisoformat(row["approved_at"]),
                    notes=row["notes"],
                    content_hash=row["content_hash"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return records

    def get_fact(self, profile_version: str, fact_id: uuid.UUID) -> CandidateFact | None:
        """Retrieve exact historical fact by profile_version and fact_id."""
        cursor = self.conn.execute(
            "SELECT fact_json FROM profile_facts WHERE profile_version = ? AND fact_id = ?",
            (profile_version, str(fact_id)),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return CandidateFact.model_validate_json(row["fact_json"])

    def list_facts_for_version(self, profile_version: str) -> list[CandidateFact]:
        """List all facts belonging to a specific published version."""
        cursor = self.conn.execute(
            "SELECT fact_json FROM profile_facts WHERE profile_version = ?",
            (profile_version,),
        )
        return [CandidateFact.model_validate_json(row["fact_json"]) for row in cursor.fetchall()]
