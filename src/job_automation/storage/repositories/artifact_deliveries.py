"""Repository managing durable delivery intents, attempts, remote mappings, access receipts, and delivery set receipts (GEN-06-S02)."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.artifacts import Artifact
from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliveryAttempt,
    DeliveryIntent,
    DeliverySetReceipt,
    RemoteArtifactMapping,
)
from job_automation.generation.records import ArtifactDeliveryRecord
from job_automation.storage.connection import transaction
from job_automation.storage.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ArtifactDeliveryRepository(BaseRepository):
    """Manages persistence, recovery, and atomic commitment of artifact delivery lifecycle."""

    def save_intent(self, intent: DeliveryIntent) -> DeliveryIntent:
        """Persist a new delivery intent or return existing matching intent."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO delivery_intents (
                    intent_id, org_id, salesforce_request_id, canonical_salesforce_id,
                    request_id, artifact_set_id, artifact_id, artifact_version,
                    artifact_format, content_hash, size_bytes, local_path,
                    reconciliation_marker, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, request_id, artifact_id, artifact_version) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (
                    str(intent.intent_id),
                    intent.org_id,
                    intent.salesforce_request_id,
                    intent.canonical_salesforce_id,
                    str(intent.request_id),
                    str(intent.artifact_set_id),
                    str(intent.artifact_id),
                    intent.artifact_version,
                    intent.artifact_format,
                    intent.content_hash,
                    intent.size_bytes,
                    intent.local_path,
                    intent.reconciliation_marker,
                    intent.status,
                    intent.created_at.isoformat(),
                    intent.updated_at.isoformat(),
                ),
            )
        return (
            self.get_intent_by_logical_key(
                intent.org_id,
                intent.request_id,
                intent.artifact_id,
                intent.artifact_version,
            )
            or intent
        )

    def get_intent(self, intent_id: uuid.UUID) -> DeliveryIntent | None:
        """Lookup delivery intent by its unique UUID."""
        row = self.conn.execute(
            "SELECT * FROM delivery_intents WHERE intent_id = ?",
            (str(intent_id),),
        ).fetchone()
        if not row:
            return None
        return self._row_to_intent(row)

    def get_intent_by_logical_key(
        self,
        org_id: str,
        request_id: uuid.UUID,
        artifact_id: uuid.UUID,
        artifact_version: int,
    ) -> DeliveryIntent | None:
        """Lookup delivery intent by org, request, artifact, and version."""
        row = self.conn.execute(
            """
            SELECT * FROM delivery_intents
            WHERE org_id = ? AND request_id = ? AND artifact_id = ? AND artifact_version = ?
            """,
            (org_id, str(request_id), str(artifact_id), artifact_version),
        ).fetchone()
        if not row:
            return None
        return self._row_to_intent(row)

    def get_intent_by_marker(self, org_id: str, marker: str) -> DeliveryIntent | None:
        """Lookup delivery intent by org and exact reconciliation marker."""
        row = self.conn.execute(
            "SELECT * FROM delivery_intents WHERE org_id = ? AND reconciliation_marker = ?",
            (org_id, marker),
        ).fetchone()
        if not row:
            return None
        return self._row_to_intent(row)

    def list_intents_for_request(self, request_id: uuid.UUID) -> list[DeliveryIntent]:
        """List all delivery intents for a generation request."""
        rows = self.conn.execute(
            "SELECT * FROM delivery_intents WHERE request_id = ? ORDER BY artifact_version ASC, artifact_format ASC",
            (str(request_id),),
        ).fetchall()
        return [self._row_to_intent(r) for r in rows]

    def update_intent_status(self, intent_id: uuid.UUID, status: str) -> None:
        """Update delivery intent status and updated_at timestamp."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE delivery_intents SET status = ?, updated_at = ? WHERE intent_id = ?",
                (status, now_utc, str(intent_id)),
            )

    def record_attempt(self, attempt: DeliveryAttempt) -> None:
        """Record a physical attempt trace row."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO delivery_attempts (
                    attempt_id, intent_id, request_id, attempt_sequence, operation_kind,
                    phase, started_at, completed_at, status, exit_code,
                    duration_ms, error_json, outcome_evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(attempt.attempt_id),
                    str(attempt.intent_id),
                    str(attempt.request_id),
                    attempt.attempt_sequence,
                    attempt.operation_kind,
                    attempt.phase,
                    attempt.started_at.isoformat(),
                    attempt.completed_at.isoformat() if attempt.completed_at else None,
                    attempt.status,
                    attempt.exit_code,
                    attempt.duration_ms,
                    json.dumps(attempt.error_json) if attempt.error_json else None,
                    json.dumps(attempt.outcome_evidence) if attempt.outcome_evidence else None,
                ),
            )

    def list_attempts_for_intent(self, intent_id: uuid.UUID) -> list[DeliveryAttempt]:
        """List all logged attempts for a given delivery intent ordered by sequence."""
        rows = self.conn.execute(
            """
            SELECT * FROM delivery_attempts
            WHERE intent_id = ?
            ORDER BY attempt_sequence ASC
            """,
            (str(intent_id),),
        ).fetchall()
        attempts: list[DeliveryAttempt] = []
        for r in rows:
            attempts.append(
                DeliveryAttempt(
                    attempt_id=uuid.UUID(r["attempt_id"]),
                    intent_id=uuid.UUID(r["intent_id"]),
                    request_id=uuid.UUID(r["request_id"]),
                    attempt_sequence=r["attempt_sequence"],
                    operation_kind=r["operation_kind"],
                    phase=r["phase"],
                    started_at=datetime.fromisoformat(r["started_at"]),
                    completed_at=datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
                    status=r["status"],
                    exit_code=r["exit_code"],
                    duration_ms=r["duration_ms"],
                    error_json=json.loads(r["error_json"]) if r["error_json"] else None,
                    outcome_evidence=json.loads(r["outcome_evidence_json"]) if r["outcome_evidence_json"] else None,
                )
            )
        return attempts

    def save_remote_mapping(self, mapping: RemoteArtifactMapping) -> None:
        """Persist or update an authoritative remote artifact mapping."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO remote_artifact_mappings (
                    mapping_id, intent_id, request_id, artifact_id, artifact_version,
                    artifact_format, content_hash, org_id, content_document_id,
                    content_version_id, provider_version_label, marker,
                    target_record_id, link_id, acknowledged_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, request_id, artifact_id, artifact_version) DO UPDATE SET
                    content_document_id = excluded.content_document_id,
                    content_version_id = excluded.content_version_id,
                    provider_version_label = excluded.provider_version_label,
                    link_id = excluded.link_id,
                    acknowledged_at = excluded.acknowledged_at
                """,
                (
                    str(mapping.mapping_id),
                    str(mapping.intent_id),
                    str(mapping.request_id),
                    str(mapping.artifact_id),
                    mapping.artifact_version,
                    mapping.artifact_format,
                    mapping.content_hash,
                    mapping.org_id,
                    mapping.content_document_id,
                    mapping.content_version_id,
                    mapping.provider_version_label,
                    mapping.marker,
                    mapping.target_record_id,
                    mapping.link_id,
                    mapping.acknowledged_at.isoformat(),
                ),
            )

    def get_remote_mapping(
        self,
        org_id: str,
        request_id: uuid.UUID,
        artifact_id: uuid.UUID,
        artifact_version: int,
    ) -> RemoteArtifactMapping | None:
        """Lookup remote artifact mapping by org, request, artifact, and version."""
        row = self.conn.execute(
            """
            SELECT * FROM remote_artifact_mappings
            WHERE org_id = ? AND request_id = ? AND artifact_id = ? AND artifact_version = ?
            """,
            (org_id, str(request_id), str(artifact_id), artifact_version),
        ).fetchone()
        if not row:
            return None
        return self._row_to_mapping(row)

    def get_remote_mapping_by_marker(
        self, org_id: str, marker: str
    ) -> RemoteArtifactMapping | None:
        """Lookup remote artifact mapping by org and exact marker."""
        row = self.conn.execute(
            "SELECT * FROM remote_artifact_mappings WHERE org_id = ? AND marker = ?",
            (org_id, marker),
        ).fetchone()
        if not row:
            return None
        return self._row_to_mapping(row)

    def list_remote_mappings_for_request(
        self, request_id: uuid.UUID
    ) -> list[RemoteArtifactMapping]:
        """List all remote artifact mappings for a request."""
        rows = self.conn.execute(
            "SELECT * FROM remote_artifact_mappings WHERE request_id = ? ORDER BY artifact_version ASC, artifact_format ASC",
            (str(request_id),),
        ).fetchall()
        return [self._row_to_mapping(r) for r in rows]

    def save_accessibility_receipt(self, receipt: AccessibilityReceipt) -> None:
        """Persist or update an accessibility proof receipt."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO accessibility_receipts (
                    receipt_id, mapping_id, request_id, artifact_id, artifact_version,
                    artifact_format, content_version_id, content_document_id,
                    target_record_id, verification_method, candidate_principal,
                    verified_at, receipt_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, artifact_version, artifact_format) DO UPDATE SET
                    content_version_id = excluded.content_version_id,
                    content_document_id = excluded.content_document_id,
                    verified_at = excluded.verified_at,
                    receipt_hash = excluded.receipt_hash
                """,
                (
                    str(receipt.receipt_id),
                    str(receipt.mapping_id),
                    str(receipt.request_id),
                    str(receipt.artifact_id),
                    receipt.artifact_version,
                    receipt.artifact_format,
                    receipt.content_version_id,
                    receipt.content_document_id,
                    receipt.target_record_id,
                    receipt.verification_method,
                    receipt.candidate_principal,
                    receipt.verified_at.isoformat(),
                    receipt.receipt_hash,
                ),
            )

    def get_accessibility_receipt(
        self,
        request_id: uuid.UUID,
        artifact_version: int,
        artifact_format: str,
    ) -> AccessibilityReceipt | None:
        """Lookup accessibility receipt for request, version, and format."""
        row = self.conn.execute(
            """
            SELECT * FROM accessibility_receipts
            WHERE request_id = ? AND artifact_version = ? AND artifact_format = ?
            """,
            (str(request_id), artifact_version, artifact_format),
        ).fetchone()
        if not row:
            return None
        return self._row_to_receipt(row)

    def list_accessibility_receipts_for_request(
        self, request_id: uuid.UUID
    ) -> list[AccessibilityReceipt]:
        """List all accessibility receipts for a request."""
        rows = self.conn.execute(
            "SELECT * FROM accessibility_receipts WHERE request_id = ? ORDER BY artifact_version ASC, artifact_format ASC",
            (str(request_id),),
        ).fetchall()
        return [self._row_to_receipt(r) for r in rows]

    def commit_delivery_set_receipt(self, set_receipt: DeliverySetReceipt) -> None:
        """Persist or update delivery set receipt."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO delivery_set_receipts (
                    set_receipt_id, request_id, set_id, set_version, required_formats_json,
                    is_accessible, review_route, created_at, receipt_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, set_version) DO UPDATE SET
                    is_accessible = excluded.is_accessible,
                    review_route = excluded.review_route,
                    receipt_hash = excluded.receipt_hash
                """,
                (
                    str(set_receipt.set_receipt_id),
                    str(set_receipt.request_id),
                    str(set_receipt.set_id),
                    set_receipt.set_version,
                    json.dumps(set_receipt.required_formats),
                    1 if set_receipt.is_accessible else 0,
                    set_receipt.review_route,
                    set_receipt.created_at.isoformat(),
                    set_receipt.receipt_hash,
                ),
            )

    def get_delivery_set_receipt(
        self, request_id: uuid.UUID, set_version: int = 1
    ) -> DeliverySetReceipt | None:
        """Fetch DeliverySetReceipt for a request and set version."""
        row = self.conn.execute(
            """
            SELECT * FROM delivery_set_receipts
            WHERE request_id = ? AND set_version = ?
            """,
            (str(request_id), set_version),
        ).fetchone()
        if not row:
            return None

        # Rehydrate associated mappings and accessibility receipts
        mappings = {
            m.artifact_format: m
            for m in self.list_remote_mappings_for_request(request_id)
            if m.artifact_version == set_version
        }
        access_receipts = {
            a.artifact_format: a
            for a in self.list_accessibility_receipts_for_request(request_id)
            if a.artifact_version == set_version
        }

        return DeliverySetReceipt(
            set_receipt_id=uuid.UUID(row["set_receipt_id"]),
            request_id=uuid.UUID(row["request_id"]),
            set_id=uuid.UUID(row["set_id"]),
            set_version=row["set_version"],
            required_formats=json.loads(row["required_formats_json"]),
            mappings=mappings,
            accessibility_receipts=access_receipts,
            is_accessible=bool(row["is_accessible"]),
            review_route=row["review_route"],
            created_at=datetime.fromisoformat(row["created_at"]),
            receipt_hash=row["receipt_hash"],
        )

    def commit_format_delivery(
        self,
        intent: DeliveryIntent,
        mapping: RemoteArtifactMapping,
        access_receipt: AccessibilityReceipt,
        artifact: Artifact,
        delivery_slot: ArtifactDeliveryRecord,
    ) -> None:
        """Atomically commit successful delivery and verification of a single format."""
        with transaction(self.conn):
            # 1. Update intent status
            self.conn.execute(
                "UPDATE delivery_intents SET status = ?, updated_at = ? WHERE intent_id = ?",
                ("delivered", datetime.now(timezone.utc).isoformat(), str(intent.intent_id)),
            )

            # 2. Insert or update remote artifact mapping
            self.conn.execute(
                """
                INSERT INTO remote_artifact_mappings (
                    mapping_id, intent_id, request_id, artifact_id, artifact_version,
                    artifact_format, content_hash, org_id, content_document_id,
                    content_version_id, provider_version_label, marker,
                    target_record_id, link_id, acknowledged_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id, request_id, artifact_id, artifact_version) DO UPDATE SET
                    content_document_id = excluded.content_document_id,
                    content_version_id = excluded.content_version_id,
                    link_id = excluded.link_id,
                    acknowledged_at = excluded.acknowledged_at
                """,
                (
                    str(mapping.mapping_id),
                    str(mapping.intent_id),
                    str(mapping.request_id),
                    str(mapping.artifact_id),
                    mapping.artifact_version,
                    mapping.artifact_format,
                    mapping.content_hash,
                    mapping.org_id,
                    mapping.content_document_id,
                    mapping.content_version_id,
                    mapping.provider_version_label,
                    mapping.marker,
                    mapping.target_record_id,
                    mapping.link_id,
                    mapping.acknowledged_at.isoformat(),
                ),
            )

            # 3. Insert or update accessibility receipt
            self.conn.execute(
                """
                INSERT INTO accessibility_receipts (
                    receipt_id, mapping_id, request_id, artifact_id, artifact_version,
                    artifact_format, content_version_id, content_document_id,
                    target_record_id, verification_method, candidate_principal,
                    verified_at, receipt_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, artifact_version, artifact_format) DO UPDATE SET
                    content_version_id = excluded.content_version_id,
                    content_document_id = excluded.content_document_id,
                    verified_at = excluded.verified_at,
                    receipt_hash = excluded.receipt_hash
                """,
                (
                    str(access_receipt.receipt_id),
                    str(access_receipt.mapping_id),
                    str(access_receipt.request_id),
                    str(access_receipt.artifact_id),
                    access_receipt.artifact_version,
                    access_receipt.artifact_format,
                    access_receipt.content_version_id,
                    access_receipt.content_document_id,
                    access_receipt.target_record_id,
                    access_receipt.verification_method,
                    access_receipt.candidate_principal,
                    access_receipt.verified_at.isoformat(),
                    access_receipt.receipt_hash,
                ),
            )

            # 4. Update C14 Artifact row with remote_file_id and delivery_status
            delivered_art = artifact.model_copy(
                update={
                    "remote_file_id": mapping.content_version_id,
                    "delivery_status": "delivered",
                    "reconciliation_marker": mapping.marker,
                }
            )
            self.conn.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                    artifact_id, request_id, artifact_version, format, local_path,
                    content_hash, size_bytes, remote_file_id, delivery_status,
                    approval_status, reconciliation_marker, created_at, artifact_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(delivered_art.artifact_id),
                    str(delivered_art.request_id),
                    delivered_art.artifact_version,
                    delivered_art.format,
                    delivered_art.local_path,
                    delivered_art.content_hash,
                    delivered_art.size_bytes,
                    delivered_art.remote_file_id,
                    delivered_art.delivery_status,
                    delivered_art.approval_status.value
                    if hasattr(delivered_art.approval_status, "value")
                    else str(delivered_art.approval_status),
                    delivered_art.reconciliation_marker,
                    delivered_art.created_at.isoformat(),
                    delivered_art.model_dump_json(),
                ),
            )

            # 5. Update generation_artifact_deliveries slot pointer
            now_iso = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                """
                INSERT INTO generation_artifact_deliveries (
                    delivery_id, request_id, artifact_format, artifact_id, artifact_hash,
                    remote_file_id, delivery_status, delivered_at, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, artifact_format) DO UPDATE SET
                    artifact_id = excluded.artifact_id,
                    artifact_hash = excluded.artifact_hash,
                    remote_file_id = excluded.remote_file_id,
                    delivery_status = excluded.delivery_status,
                    delivered_at = excluded.delivered_at,
                    receipt_json = excluded.receipt_json
                """,
                (
                    str(delivery_slot.delivery_id),
                    str(delivery_slot.request_id),
                    delivery_slot.artifact_format,
                    str(delivery_slot.artifact_id),
                    delivery_slot.artifact_hash,
                    mapping.content_version_id,
                    "delivered",
                    now_iso,
                    json.dumps(
                        {
                            "content_document_id": mapping.content_document_id,
                            "content_version_id": mapping.content_version_id,
                            "marker": mapping.marker,
                            "link_id": mapping.link_id,
                            "accessibility_receipt_id": str(access_receipt.receipt_id),
                        }
                    ),
                ),
            )

    @staticmethod
    def _row_to_intent(row: sqlite3.Row) -> DeliveryIntent:
        return DeliveryIntent(
            intent_id=uuid.UUID(row["intent_id"]),
            org_id=row["org_id"],
            salesforce_request_id=row["salesforce_request_id"],
            canonical_salesforce_id=row["canonical_salesforce_id"],
            request_id=uuid.UUID(row["request_id"]),
            artifact_set_id=uuid.UUID(row["artifact_set_id"]),
            artifact_id=uuid.UUID(row["artifact_id"]),
            artifact_version=row["artifact_version"],
            artifact_format=row["artifact_format"],
            content_hash=row["content_hash"],
            size_bytes=row["size_bytes"],
            local_path=row["local_path"],
            reconciliation_marker=row["reconciliation_marker"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_mapping(row: sqlite3.Row) -> RemoteArtifactMapping:
        return RemoteArtifactMapping(
            mapping_id=uuid.UUID(row["mapping_id"]),
            intent_id=uuid.UUID(row["intent_id"]),
            request_id=uuid.UUID(row["request_id"]),
            artifact_id=uuid.UUID(row["artifact_id"]),
            artifact_version=row["artifact_version"],
            artifact_format=row["artifact_format"],
            content_hash=row["content_hash"],
            org_id=row["org_id"],
            content_document_id=row["content_document_id"],
            content_version_id=row["content_version_id"],
            provider_version_label=row["provider_version_label"],
            marker=row["marker"],
            target_record_id=row["target_record_id"],
            link_id=row["link_id"],
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]),
        )

    @staticmethod
    def _row_to_receipt(row: sqlite3.Row) -> AccessibilityReceipt:
        return AccessibilityReceipt(
            receipt_id=uuid.UUID(row["receipt_id"]),
            mapping_id=uuid.UUID(row["mapping_id"]),
            request_id=uuid.UUID(row["request_id"]),
            artifact_id=uuid.UUID(row["artifact_id"]),
            artifact_version=row["artifact_version"],
            artifact_format=row["artifact_format"],
            content_version_id=row["content_version_id"],
            content_document_id=row["content_document_id"],
            target_record_id=row["target_record_id"],
            verification_method=row["verification_method"],
            candidate_principal=row["candidate_principal"],
            verified_at=datetime.fromisoformat(row["verified_at"]),
            receipt_hash=row["receipt_hash"],
        )

