"""Identity repository managing companies, source mappings, observations, review cases, and merge events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.primitives import SourceKey
from job_automation.storage.connection import transaction
from job_automation.storage.repositories.base import BaseRepository


class IdentityRepository(BaseRepository):
    """Storage repository for IDENTITY-01 tables created in migration 004."""

    # -------------------------------------------------------------------------
    # Company entities & aliases
    # -------------------------------------------------------------------------

    def save_company(
        self,
        company_id: uuid.UUID,
        canonical_name: str,
        normalized_name: str,
    ) -> None:
        """Persist or update a canonical company entity."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO companies (
                    company_id, canonical_name, normalized_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(company_id) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    normalized_name = excluded.normalized_name,
                    updated_at = excluded.updated_at
                """,
                (str(company_id), canonical_name, normalized_name, now_utc, now_utc),
            )

    def get_company(self, company_id: uuid.UUID) -> dict[str, Any] | None:
        """Fetch company entity by UUID."""
        cursor = self.conn.execute(
            """
            SELECT company_id, canonical_name, normalized_name, created_at, updated_at
            FROM companies WHERE company_id = ?
            """,
            (str(company_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def find_company_by_name(self, normalized_name: str) -> dict[str, Any] | None:
        """Find company by exact normalized name."""
        cursor = self.conn.execute(
            """
            SELECT company_id, canonical_name, normalized_name, created_at, updated_at
            FROM companies WHERE normalized_name = ?
            LIMIT 1
            """,
            (normalized_name,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def save_company_alias(
        self,
        company_id: uuid.UUID,
        namespace: str,
        alias_key: str,
    ) -> None:
        """Record a reviewed or namespaced alias for a company."""
        now_utc = datetime.now(timezone.utc).isoformat()
        alias_id = str(uuid.uuid4())
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO company_aliases (
                    alias_id, company_id, namespace, alias_key, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(namespace, alias_key) DO UPDATE SET
                    company_id = excluded.company_id
                """,
                (alias_id, str(company_id), namespace, alias_key, now_utc),
            )

    def find_company_by_alias(self, namespace: str, alias_key: str) -> uuid.UUID | None:
        """Lookup company UUID by namespaced alias key."""
        cursor = self.conn.execute(
            """
            SELECT company_id FROM company_aliases
            WHERE namespace = ? AND alias_key = ?
            LIMIT 1
            """,
            (namespace, alias_key),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return uuid.UUID(row["company_id"])

    # -------------------------------------------------------------------------
    # Source identity mappings
    # -------------------------------------------------------------------------

    def save_source_identity(
        self,
        source_key: SourceKey,
        canonical_job_id: uuid.UUID,
        first_seen_at: datetime,
        last_seen_at: datetime,
    ) -> None:
        """Map a source identity tuple to a canonical job."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
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
                    source_key.provider,
                    source_key.board_id,
                    source_key.source_posting_id,
                    str(canonical_job_id),
                    first_seen_at.isoformat(),
                    last_seen_at.isoformat(),
                    now_utc,
                    now_utc,
                ),
            )

    def get_canonical_id_for_source_key(self, source_key: SourceKey) -> uuid.UUID | None:
        """Lookup canonical job UUID mapped to a source key."""
        cursor = self.conn.execute(
            """
            SELECT canonical_job_id FROM source_identities
            WHERE provider = ? AND board_id = ? AND source_posting_id = ?
            LIMIT 1
            """,
            (source_key.provider, source_key.board_id, source_key.source_posting_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return uuid.UUID(row["canonical_job_id"])

    def get_source_keys_for_canonical_id(self, canonical_job_id: uuid.UUID) -> list[SourceKey]:
        """Fetch all source keys currently mapped to a canonical job."""
        cursor = self.conn.execute(
            """
            SELECT provider, board_id, source_posting_id
            FROM source_identities
            WHERE canonical_job_id = ?
            ORDER BY first_seen_at ASC
            """,
            (str(canonical_job_id),),
        )
        return [
            SourceKey(
                provider=row["provider"],
                board_id=row["board_id"],
                source_posting_id=row["source_posting_id"],
            )
            for row in cursor.fetchall()
        ]

    def reassign_source_key(
        self,
        source_key: SourceKey,
        new_canonical_job_id: uuid.UUID,
        updated_at: datetime | None = None,
    ) -> None:
        """Update source mapping to point to another canonical job."""
        now_utc = (updated_at or datetime.now(timezone.utc)).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                UPDATE source_identities
                SET canonical_job_id = ?, updated_at = ?
                WHERE provider = ? AND board_id = ? AND source_posting_id = ?
                """,
                (
                    str(new_canonical_job_id),
                    now_utc,
                    source_key.provider,
                    source_key.board_id,
                    source_key.source_posting_id,
                ),
            )

    # -------------------------------------------------------------------------
    # Posting observations
    # -------------------------------------------------------------------------

    def save_observation(
        self,
        observation_id: uuid.UUID,
        canonical_job_id: uuid.UUID,
        revision_id: uuid.UUID,
        source_key: SourceKey,
        raw_reference: str,
        raw_content_hash: str,
        observed_at: datetime,
    ) -> None:
        """Record an immutable observation of a source posting."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO posting_observations (
                    observation_id, canonical_job_id, revision_id,
                    provider, board_id, source_posting_id,
                    raw_reference, raw_content_hash, observed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(observation_id),
                    str(canonical_job_id),
                    str(revision_id),
                    source_key.provider,
                    source_key.board_id,
                    source_key.source_posting_id,
                    raw_reference,
                    raw_content_hash,
                    observed_at.isoformat(),
                    now_utc,
                ),
            )

    def get_observations(self, canonical_job_id: uuid.UUID) -> list[dict[str, Any]]:
        """Return all observations for a canonical job in chronological order."""
        cursor = self.conn.execute(
            """
            SELECT observation_id, canonical_job_id, revision_id,
                   provider, board_id, source_posting_id,
                   raw_reference, raw_content_hash, observed_at, created_at
            FROM posting_observations
            WHERE canonical_job_id = ?
            ORDER BY observed_at ASC
            """,
            (str(canonical_job_id),),
        )
        return [dict(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Identity review cases
    # -------------------------------------------------------------------------

    def save_review_case(
        self,
        case_id: str,
        status: str,
        reason: str,
        candidate_job_ids: list[uuid.UUID],
        source_key: SourceKey,
        evidence: dict[str, Any],
        decision_actor: str | None = None,
        decision_reason: str | None = None,
        decided_at: datetime | None = None,
    ) -> None:
        """Persist or update an identity review case."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO identity_review_cases (
                    case_id, status, reason, candidate_job_ids_json,
                    source_key_json, evidence_json, decision_actor,
                    decision_reason, decided_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    candidate_job_ids_json = excluded.candidate_job_ids_json,
                    source_key_json = excluded.source_key_json,
                    evidence_json = excluded.evidence_json,
                    decision_actor = excluded.decision_actor,
                    decision_reason = excluded.decision_reason,
                    decided_at = excluded.decided_at,
                    updated_at = excluded.updated_at
                """,
                (
                    case_id,
                    status,
                    reason,
                    json.dumps([str(cid) for cid in candidate_job_ids]),
                    json.dumps(source_key.model_dump()),
                    json.dumps(evidence),
                    decision_actor,
                    decision_reason,
                    decided_at.isoformat() if decided_at else None,
                    now_utc,
                    now_utc,
                ),
            )

    def get_review_case(self, case_id: str) -> dict[str, Any] | None:
        """Fetch a review case by ID."""
        cursor = self.conn.execute(
            """
            SELECT case_id, status, reason, candidate_job_ids_json,
                   source_key_json, evidence_json, decision_actor,
                   decision_reason, decided_at, created_at, updated_at
            FROM identity_review_cases
            WHERE case_id = ?
            """,
            (case_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        res["candidate_job_ids"] = [
            uuid.UUID(uid) for uid in json.loads(res.pop("candidate_job_ids_json"))
        ]
        res["source_key"] = SourceKey.model_validate(json.loads(res.pop("source_key_json")))
        res["evidence"] = json.loads(res.pop("evidence_json"))
        return res

    def list_review_cases(self, status: str | None = None) -> list[dict[str, Any]]:
        """List review cases, optionally filtered by status."""
        if status:
            cursor = self.conn.execute(
                """
                SELECT case_id, status, reason, candidate_job_ids_json,
                       source_key_json, evidence_json, decision_actor,
                       decision_reason, decided_at, created_at, updated_at
                FROM identity_review_cases
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (status,),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT case_id, status, reason, candidate_job_ids_json,
                       source_key_json, evidence_json, decision_actor,
                       decision_reason, decided_at, created_at, updated_at
                FROM identity_review_cases
                ORDER BY created_at DESC
                """
            )

        results: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            item = dict(row)
            item["candidate_job_ids"] = [
                uuid.UUID(uid) for uid in json.loads(item.pop("candidate_job_ids_json"))
            ]
            item["source_key"] = SourceKey.model_validate(json.loads(item.pop("source_key_json")))
            item["evidence"] = json.loads(item.pop("evidence_json"))
            results.append(item)
        return results

    def find_pending_review_case(
        self,
        source_key: SourceKey,
        candidate_job_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Find an existing pending review case for this source key and candidate job."""
        cases = self.list_review_cases(status="pending")
        for case in cases:
            if case["source_key"] == source_key and candidate_job_id in case["candidate_job_ids"]:
                return case
        return None

    def update_review_case_status(
        self,
        case_id: str,
        status: str,
        actor: str,
        reason: str,
        decided_at: datetime | None = None,
    ) -> None:
        """Record human decision on a review case."""
        now_dt = decided_at or datetime.now(timezone.utc)
        now_utc = now_dt.isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                UPDATE identity_review_cases
                SET status = ?, decision_actor = ?, decision_reason = ?,
                    decided_at = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (status, actor, reason, now_utc, now_utc, case_id),
            )

    # -------------------------------------------------------------------------
    # Identity merge events
    # -------------------------------------------------------------------------

    def save_merge_event(
        self,
        operation_id: str,
        operation_type: str,
        surviving_canonical_id: uuid.UUID,
        merged_canonical_id: uuid.UUID,
        actor: str,
        reason: str,
        details: dict[str, Any],
        reversed_by_operation_id: str | None = None,
        reversed_at: datetime | None = None,
    ) -> None:
        """Persist an append-only merge or reversal event."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO identity_merge_events (
                    operation_id, operation_type, surviving_canonical_id,
                    merged_canonical_id, actor, reason, details_json,
                    reversed_by_operation_id, created_at, reversed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation_id) DO UPDATE SET
                    reversed_by_operation_id = excluded.reversed_by_operation_id,
                    reversed_at = excluded.reversed_at
                """,
                (
                    operation_id,
                    operation_type,
                    str(surviving_canonical_id),
                    str(merged_canonical_id),
                    actor,
                    reason,
                    json.dumps(details),
                    reversed_by_operation_id,
                    now_utc,
                    reversed_at.isoformat() if reversed_at else None,
                ),
            )

    def get_merge_event(self, operation_id: str) -> dict[str, Any] | None:
        """Fetch a merge event by operation ID."""
        cursor = self.conn.execute(
            """
            SELECT operation_id, operation_type, surviving_canonical_id,
                   merged_canonical_id, actor, reason, details_json,
                   reversed_by_operation_id, created_at, reversed_at
            FROM identity_merge_events
            WHERE operation_id = ?
            """,
            (operation_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        res["surviving_canonical_id"] = uuid.UUID(res["surviving_canonical_id"])
        res["merged_canonical_id"] = uuid.UUID(res["merged_canonical_id"])
        res["details"] = json.loads(res.pop("details_json"))
        return res

    def mark_merge_event_reversed(
        self,
        operation_id: str,
        reversed_by_operation_id: str,
        reversed_at: datetime,
    ) -> None:
        """Mark a merge event as reversed."""
        now_utc = reversed_at.isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                UPDATE identity_merge_events
                SET reversed_by_operation_id = ?, reversed_at = ?
                WHERE operation_id = ?
                """,
                (reversed_by_operation_id, now_utc, operation_id),
            )

    def list_merge_events(self) -> list[dict[str, Any]]:
        """List all merge events in chronological order."""
        cursor = self.conn.execute(
            """
            SELECT operation_id, operation_type, surviving_canonical_id,
                   merged_canonical_id, actor, reason, details_json,
                   reversed_by_operation_id, created_at, reversed_at
            FROM identity_merge_events
            ORDER BY created_at ASC
            """
        )
        events: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            res = dict(row)
            res["surviving_canonical_id"] = uuid.UUID(res["surviving_canonical_id"])
            res["merged_canonical_id"] = uuid.UUID(res["merged_canonical_id"])
            res["details"] = json.loads(res.pop("details_json"))
            events.append(res)
        return events
