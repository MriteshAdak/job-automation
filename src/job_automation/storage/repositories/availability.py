"""Storage repository for IDENTITY-02 availability tracking tables."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    SourcePostingAvailability,
)
from job_automation.storage.connection import transaction
from job_automation.storage.repositories.base import BaseRepository


class AvailabilityRepository(BaseRepository):
    """Storage repository managing source_posting_availability, availability_decisions, and consumed_inventories."""

    # -------------------------------------------------------------------------
    # Source posting availability
    # -------------------------------------------------------------------------

    def save_source_availability(self, item: SourcePostingAvailability) -> None:
        """Persist or update a per-scope source posting availability record."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO source_posting_availability (
                    provider, board_id, source_posting_id, scope_id,
                    canonical_job_id, availability, first_seen_at, last_seen_at,
                    missing_since, miss_count, policy_fingerprint, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, board_id, source_posting_id, scope_id) DO UPDATE SET
                    canonical_job_id = coalesce(excluded.canonical_job_id, source_posting_availability.canonical_job_id),
                    availability = excluded.availability,
                    last_seen_at = excluded.last_seen_at,
                    missing_since = excluded.missing_since,
                    miss_count = excluded.miss_count,
                    policy_fingerprint = excluded.policy_fingerprint,
                    updated_at = excluded.updated_at
                """,
                (
                    item.source_key.provider,
                    item.source_key.board_id,
                    item.source_key.source_posting_id,
                    item.scope_id,
                    str(item.canonical_job_id) if item.canonical_job_id else None,
                    item.availability.value,
                    item.first_seen_at.isoformat(),
                    item.last_seen_at.isoformat(),
                    item.missing_since.isoformat() if item.missing_since else None,
                    item.miss_count,
                    item.policy_fingerprint,
                    now_utc,
                    now_utc,
                ),
            )

    def get_source_availability(
        self, source_key: SourceKey, scope_id: str
    ) -> SourcePostingAvailability | None:
        """Fetch availability state for a source posting in a specific scope."""
        cursor = self.conn.execute(
            """
            SELECT provider, board_id, source_posting_id, scope_id,
                   canonical_job_id, availability, first_seen_at, last_seen_at,
                   missing_since, miss_count, policy_fingerprint
            FROM source_posting_availability
            WHERE provider = ? AND board_id = ? AND source_posting_id = ? AND scope_id = ?
            LIMIT 1
            """,
            (source_key.provider, source_key.board_id, source_key.source_posting_id, scope_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_source_posting_availability(row)

    def list_scope_baseline(self, scope_id: str) -> list[SourcePostingAvailability]:
        """Fetch all source postings enrolled in a specific scope baseline."""
        cursor = self.conn.execute(
            """
            SELECT provider, board_id, source_posting_id, scope_id,
                   canonical_job_id, availability, first_seen_at, last_seen_at,
                   missing_since, miss_count, policy_fingerprint
            FROM source_posting_availability
            WHERE scope_id = ?
            ORDER BY first_seen_at ASC
            """,
            (scope_id,),
        )
        return [self._row_to_source_posting_availability(row) for row in cursor.fetchall()]

    def list_for_canonical_job(
        self, canonical_job_id: uuid.UUID
    ) -> list[SourcePostingAvailability]:
        """Fetch all source posting availability records mapped to a canonical job."""
        cursor = self.conn.execute(
            """
            SELECT provider, board_id, source_posting_id, scope_id,
                   canonical_job_id, availability, first_seen_at, last_seen_at,
                   missing_since, miss_count, policy_fingerprint
            FROM source_posting_availability
            WHERE canonical_job_id = ?
            ORDER BY last_seen_at DESC
            """,
            (str(canonical_job_id),),
        )
        return [self._row_to_source_posting_availability(row) for row in cursor.fetchall()]

    def list_for_source_key(
        self, source_key: SourceKey
    ) -> list[SourcePostingAvailability]:
        """Fetch availability records across all scopes for a source posting tuple."""
        cursor = self.conn.execute(
            """
            SELECT provider, board_id, source_posting_id, scope_id,
                   canonical_job_id, availability, first_seen_at, last_seen_at,
                   missing_since, miss_count, policy_fingerprint
            FROM source_posting_availability
            WHERE provider = ? AND board_id = ? AND source_posting_id = ?
            ORDER BY last_seen_at DESC
            """,
            (source_key.provider, source_key.board_id, source_key.source_posting_id),
        )
        return [self._row_to_source_posting_availability(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Availability decisions
    # -------------------------------------------------------------------------

    def record_decision(self, decision: AvailabilityDecision) -> None:
        """Append an availability transition or evaluation decision to the audit ledger."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO availability_decisions (
                    decision_id, provider, board_id, source_posting_id,
                    canonical_job_id, scope_id, manifest_id, run_id,
                    from_availability, to_availability, reason, miss_count,
                    missing_since, event_time, policy_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(decision.decision_id),
                    decision.source_key.provider,
                    decision.source_key.board_id,
                    decision.source_key.source_posting_id,
                    str(decision.canonical_job_id) if decision.canonical_job_id else None,
                    decision.scope_id,
                    decision.manifest_id,
                    str(decision.run_id) if decision.run_id else None,
                    decision.from_availability.value,
                    decision.to_availability.value,
                    decision.reason,
                    decision.miss_count,
                    decision.missing_since.isoformat() if decision.missing_since else None,
                    decision.event_time.isoformat(),
                    decision.policy_fingerprint,
                    now_utc,
                ),
            )

    def get_decisions_for_source(
        self, source_key: SourceKey, limit: int = 50
    ) -> list[AvailabilityDecision]:
        """Fetch recent decisions for a specific source posting tuple."""
        cursor = self.conn.execute(
            """
            SELECT decision_id, provider, board_id, source_posting_id,
                   canonical_job_id, scope_id, manifest_id, run_id,
                   from_availability, to_availability, reason, miss_count,
                   missing_since, event_time, policy_fingerprint
            FROM availability_decisions
            WHERE provider = ? AND board_id = ? AND source_posting_id = ?
            ORDER BY event_time DESC
            LIMIT ?
            """,
            (source_key.provider, source_key.board_id, source_key.source_posting_id, limit),
        )
        return [self._row_to_decision(row) for row in cursor.fetchall()]

    def get_decisions_for_canonical_job(
        self, canonical_job_id: uuid.UUID, limit: int = 50
    ) -> list[AvailabilityDecision]:
        """Fetch recent decisions affecting a canonical job."""
        cursor = self.conn.execute(
            """
            SELECT decision_id, provider, board_id, source_posting_id,
                   canonical_job_id, scope_id, manifest_id, run_id,
                   from_availability, to_availability, reason, miss_count,
                   missing_since, event_time, policy_fingerprint
            FROM availability_decisions
            WHERE canonical_job_id = ?
            ORDER BY event_time DESC
            LIMIT ?
            """,
            (str(canonical_job_id), limit),
        )
        return [self._row_to_decision(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Inventory consumption tracking (idempotency)
    # -------------------------------------------------------------------------

    def record_consumption(
        self,
        manifest_id: str,
        run_id: uuid.UUID,
        source_key: str,
        scope_id: str,
        outcome: str,
        inventory_semantics: str,
        manifest_hash: str,
        has_evaluated_negative: int,
        positive_count: int,
        miss_count: int,
        change_count: int,
        processed_at: datetime,
    ) -> None:
        """Record or update manifest consumption for idempotent processing."""
        consumption_id = str(uuid.uuid4())
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO consumed_inventories (
                    consumption_id, manifest_id, run_id, source_key, scope_id,
                    outcome, inventory_semantics, manifest_hash,
                    has_evaluated_negative, processed_at, positive_count,
                    miss_count, change_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, source_key, scope_id) DO UPDATE SET
                    manifest_id = excluded.manifest_id,
                    outcome = excluded.outcome,
                    inventory_semantics = excluded.inventory_semantics,
                    manifest_hash = excluded.manifest_hash,
                    has_evaluated_negative = max(consumed_inventories.has_evaluated_negative, excluded.has_evaluated_negative),
                    processed_at = excluded.processed_at,
                    positive_count = excluded.positive_count,
                    miss_count = excluded.miss_count,
                    change_count = excluded.change_count
                """,
                (
                    consumption_id,
                    manifest_id,
                    str(run_id),
                    source_key,
                    scope_id,
                    outcome,
                    inventory_semantics,
                    manifest_hash,
                    has_evaluated_negative,
                    processed_at.isoformat(),
                    positive_count,
                    miss_count,
                    change_count,
                ),
            )

    def get_consumed_inventory(
        self, run_id: uuid.UUID, source_key: str, scope_id: str
    ) -> dict[str, Any] | None:
        """Lookup previously consumed inventory record."""
        cursor = self.conn.execute(
            """
            SELECT consumption_id, manifest_id, run_id, source_key, scope_id,
                   outcome, inventory_semantics, manifest_hash,
                   has_evaluated_negative, processed_at, positive_count,
                   miss_count, change_count
            FROM consumed_inventories
            WHERE run_id = ? AND source_key = ? AND scope_id = ?
            LIMIT 1
            """,
            (str(run_id), source_key, scope_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    # -------------------------------------------------------------------------
    # Helper mappers
    # -------------------------------------------------------------------------

    def _row_to_source_posting_availability(self, row: sqlite3.Row) -> SourcePostingAvailability:
        return SourcePostingAvailability(
            source_key=SourceKey(
                provider=row["provider"],
                board_id=row["board_id"],
                source_posting_id=row["source_posting_id"],
            ),
            scope_id=row["scope_id"],
            canonical_job_id=uuid.UUID(row["canonical_job_id"]) if row["canonical_job_id"] else None,
            availability=PostingAvailability(row["availability"]),
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            missing_since=datetime.fromisoformat(row["missing_since"]) if row["missing_since"] else None,
            miss_count=int(row["miss_count"]),
            policy_fingerprint=row["policy_fingerprint"],
        )

    def _row_to_decision(self, row: sqlite3.Row) -> AvailabilityDecision:
        return AvailabilityDecision(
            decision_id=uuid.UUID(row["decision_id"]),
            source_key=SourceKey(
                provider=row["provider"],
                board_id=row["board_id"],
                source_posting_id=row["source_posting_id"],
            ),
            canonical_job_id=uuid.UUID(row["canonical_job_id"]) if row["canonical_job_id"] else None,
            scope_id=row["scope_id"],
            manifest_id=row["manifest_id"],
            run_id=uuid.UUID(row["run_id"]) if row["run_id"] else None,
            from_availability=PostingAvailability(row["from_availability"]),
            to_availability=PostingAvailability(row["to_availability"]),
            reason=row["reason"],
            miss_count=int(row["miss_count"]),
            missing_since=datetime.fromisoformat(row["missing_since"]) if row["missing_since"] else None,
            event_time=datetime.fromisoformat(row["event_time"]),
            policy_fingerprint=row["policy_fingerprint"],
        )

