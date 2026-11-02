"""Repository for automatic drafting policies, decisions, intents, reservations, and bindings."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.primitives import UtcDatetime
from job_automation.generation.automatic.records import (
    AutomaticDraftDecision,
    AutomaticDraftIntent,
    AutomaticDraftPolicy,
    AutomaticDraftReservation,
    AutomaticRequestBinding,
    ReservationStatus,
    SubmissionState,
)
from job_automation.storage.connection import _TRANSACTION_DEPTHS
from job_automation.storage.exceptions import DuplicateKeyError, RecordNotFoundError
from job_automation.storage.repositories.base import BaseRepository


class AutomaticDraftRepository(BaseRepository):
    """Manages persistence for AUTO-02 automatic drafting policies and audit history."""

    def _execute(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        """Execute a statement safely, respecting outer transactions if active."""
        depth = _TRANSACTION_DEPTHS.get(id(self.conn), 0)
        if depth > 0:
            return self.conn.execute(sql, params)
        with self.conn:
            return self.conn.execute(sql, params)

    # -------------------------------------------------------------------------
    # Policies
    # -------------------------------------------------------------------------

    def save_policy(self, policy: AutomaticDraftPolicy) -> None:
        """Save an automatic draft policy snapshot.

        If a policy with the same policy_id and policy_version exists with different content hash,
        raises ValueError (immutable version policy).
        """
        existing = self.get_policy(policy.policy_id, policy.policy_version)
        if existing is not None:
            if existing.policy_content_hash != policy.policy_content_hash:
                raise ValueError(
                    f"Policy version conflict: {policy.policy_id} {policy.policy_version} "
                    f"already exists with hash {existing.policy_content_hash}, cannot overwrite with {policy.policy_content_hash}"
                )
            # Idempotent re-save
            return

        now_utc = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            INSERT INTO auto_draft_policies (
                policy_id, policy_version, policy_content_hash, enabled,
                candidate_id, salesforce_org_id, policy_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.policy_id,
                policy.policy_version,
                policy.policy_content_hash,
                1 if policy.enabled else 0,
                str(policy.candidate_id),
                policy.salesforce_org_id,
                policy.model_dump_json(),
                now_utc,
            ),
        )

    def get_policy(self, policy_id: str, policy_version: str) -> AutomaticDraftPolicy | None:
        """Retrieve a specific versioned policy."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT policy_json FROM auto_draft_policies
            WHERE policy_id = ? AND policy_version = ?
            """,
            (policy_id, policy_version),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return AutomaticDraftPolicy.model_validate_json(row[0])

    def get_latest_policy(self, policy_id: str) -> AutomaticDraftPolicy | None:
        """Retrieve the latest registered policy for a policy_id."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT policy_json FROM auto_draft_policies
            WHERE policy_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (policy_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return AutomaticDraftPolicy.model_validate_json(row[0])

    # -------------------------------------------------------------------------
    # Decisions
    # -------------------------------------------------------------------------

    def save_decision(self, decision: AutomaticDraftDecision) -> None:
        """Save an immutable automatic draft decision record."""
        self._execute(
            """
            INSERT INTO auto_draft_decisions (
                decision_id, candidate_id, salesforce_org_id, canonical_job_id,
                evaluation_run_id, evaluation_attempt_id, policy_id, policy_version,
                policy_content_hash, decision_input_fingerprint, outcome,
                reason_codes_json, summary_reason, relevance_score,
                threshold_applied, assessment_id, client_request_key,
                decision_json, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(decision.decision_id),
                str(decision.candidate_id),
                decision.salesforce_org_id,
                str(decision.canonical_job_id),
                str(decision.evaluation_run_id),
                str(decision.evaluation_attempt_id),
                decision.policy_id,
                decision.policy_version,
                decision.policy_content_hash,
                decision.decision_input_fingerprint,
                decision.outcome.value,
                json.dumps(decision.reason_codes),
                decision.summary_reason,
                decision.relevance_score,
                decision.threshold_applied,
                str(decision.assessment_ref) if decision.assessment_ref else None,
                decision.existing_intent_key,
                decision.model_dump_json(),
                decision.evaluated_at.isoformat(),
            ),
        )

    def get_decision(self, decision_id: uuid.UUID) -> AutomaticDraftDecision | None:
        """Retrieve a decision by UUID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT decision_json FROM auto_draft_decisions WHERE decision_id = ?",
            (str(decision_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return AutomaticDraftDecision.model_validate_json(row[0])

    def list_decisions_for_job(self, canonical_job_id: uuid.UUID) -> list[AutomaticDraftDecision]:
        """List all decisions for a canonical job ordered by evaluation time."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT decision_json FROM auto_draft_decisions
            WHERE canonical_job_id = ?
            ORDER BY evaluated_at DESC
            """,
            (str(canonical_job_id),),
        )
        return [AutomaticDraftDecision.model_validate_json(row[0]) for row in cursor.fetchall()]

    def list_decisions_for_run(self, evaluation_run_id: uuid.UUID) -> list[AutomaticDraftDecision]:
        """List all decisions produced in an evaluation run."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT decision_json FROM auto_draft_decisions
            WHERE evaluation_run_id = ?
            ORDER BY evaluated_at ASC
            """,
            (str(evaluation_run_id),),
        )
        return [AutomaticDraftDecision.model_validate_json(row[0]) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Intents
    # -------------------------------------------------------------------------

    def save_intent(self, intent: AutomaticDraftIntent) -> None:
        """Save a new intent or update an existing intent.

        If client_request_key exists with a different payload digest, raises ValueError (conflict).
        """
        existing = self.get_intent_by_key(intent.client_request_key)
        if existing is not None:
            if existing.intent_id != intent.intent_id:
                if existing.request_payload_digest != intent.request_payload_digest:
                    raise ValueError(
                        f"Conflict on client_request_key '{intent.client_request_key}': "
                        f"already associated with different payload digest {existing.request_payload_digest}"
                    )
            # Update existing intent
            self._execute(
                """
                UPDATE auto_draft_intents
                SET submission_state = ?, salesforce_request_id = ?, local_request_id = ?,
                    attempt_count = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (
                    intent.submission_state.value,
                    intent.salesforce_request_id,
                    str(intent.local_request_id) if intent.local_request_id else None,
                    intent.attempt_count,
                    datetime.now(timezone.utc).isoformat(),
                    str(intent.intent_id),
                ),
            )
            return

        self._execute(
            """
            INSERT INTO auto_draft_intents (
                intent_id, client_request_key, candidate_id, salesforce_org_id,
                canonical_job_id, document_type, material_generation_fingerprint,
                policy_id, policy_version, policy_content_hash, decision_id,
                request_payload_digest, request_payload_json, submission_state,
                salesforce_request_id, local_request_id, attempt_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(intent.intent_id),
                intent.client_request_key,
                str(intent.candidate_id),
                intent.salesforce_org_id,
                str(intent.canonical_job_id),
                intent.document_type.value,
                intent.material_generation_fingerprint,
                intent.policy_id,
                intent.policy_version,
                intent.policy_content_hash,
                str(intent.decision_id),
                intent.request_payload_digest,
                intent.request_payload_json,
                intent.submission_state.value,
                intent.salesforce_request_id,
                str(intent.local_request_id) if intent.local_request_id else None,
                intent.attempt_count,
                intent.created_at.isoformat(),
                intent.updated_at.isoformat(),
            ),
        )

    def get_intent(self, intent_id: uuid.UUID) -> AutomaticDraftIntent | None:
        """Retrieve an intent by UUID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM auto_draft_intents WHERE intent_id = ?",
            (str(intent_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_intent(cursor, row)

    def get_intent_by_key(self, client_request_key: str) -> AutomaticDraftIntent | None:
        """Retrieve an intent by unique client request key."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM auto_draft_intents WHERE client_request_key = ?",
            (client_request_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_intent(cursor, row)

    def list_intents_for_job(self, canonical_job_id: uuid.UUID) -> list[AutomaticDraftIntent]:
        """List all intents created for a canonical job."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM auto_draft_intents WHERE canonical_job_id = ? ORDER BY created_at ASC",
            (str(canonical_job_id),),
        )
        return [self._row_to_intent(cursor, r) for r in cursor.fetchall()]

    def list_intents_for_fingerprint(self, material_fingerprint: str) -> list[AutomaticDraftIntent]:
        """List intents matching a specific material generation fingerprint."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM auto_draft_intents WHERE material_generation_fingerprint = ?",
            (material_fingerprint,),
        )
        return [self._row_to_intent(cursor, r) for r in cursor.fetchall()]

    def list_active_intents(self) -> list[AutomaticDraftIntent]:
        """List uncompleted / outstanding intents."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM auto_draft_intents
            WHERE submission_state IN ('reserved', 'sending', 'uncertain', 'acknowledged')
            ORDER BY created_at ASC
            """
        )
        return [self._row_to_intent(cursor, r) for r in cursor.fetchall()]

    def _row_to_intent(self, cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> AutomaticDraftIntent:
        cols = [c[0] for c in cursor.description]
        d = dict(zip(cols, row))
        payload_dict = json.loads(d["request_payload_json"])
        return AutomaticDraftIntent(
            intent_id=uuid.UUID(d["intent_id"]),
            client_request_key=d["client_request_key"],
            candidate_id=uuid.UUID(d["candidate_id"]),
            salesforce_org_id=d["salesforce_org_id"],
            canonical_job_id=uuid.UUID(d["canonical_job_id"]),
            document_type=d["document_type"],
            target_language=payload_dict.get("target_language", "de"),
            template_id=payload_dict.get("template_id", "standard-cv"),
            context_strategy=payload_dict.get("context_strategy", "json"),
            formats=payload_dict.get("formats", ["docx", "pdf"]),
            material_generation_fingerprint=d["material_generation_fingerprint"],
            policy_id=d["policy_id"],
            policy_version=d["policy_version"],
            policy_content_hash=d["policy_content_hash"],
            decision_id=uuid.UUID(d["decision_id"]),
            request_payload_digest=d["request_payload_digest"],
            request_payload_json=d["request_payload_json"],
            submission_state=d["submission_state"],
            salesforce_request_id=d["salesforce_request_id"],
            local_request_id=uuid.UUID(d["local_request_id"]) if d["local_request_id"] else None,
            attempt_count=d["attempt_count"],
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
        )

    # -------------------------------------------------------------------------
    # Reservations & Quotas
    # -------------------------------------------------------------------------

    def save_reservation(self, reservation: AutomaticDraftReservation) -> None:
        """Persist a quota reservation atomically."""
        self._execute(
            """
            INSERT INTO auto_draft_reservations (
                reservation_id, candidate_id, salesforce_org_id, canonical_job_id,
                evaluation_run_id, intent_id, client_request_key, document_units,
                status, reserved_at, released_at, release_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(reservation.reservation_id),
                str(reservation.candidate_id),
                reservation.salesforce_org_id,
                str(reservation.canonical_job_id),
                str(reservation.evaluation_run_id),
                str(reservation.intent_id),
                reservation.client_request_key,
                reservation.document_units,
                reservation.status.value,
                reservation.reserved_at.isoformat(),
                reservation.released_at.isoformat() if reservation.released_at else None,
                reservation.release_reason,
            ),
        )

    def release_reservation(self, reservation_id: uuid.UUID, reason: str) -> None:
        """Release an active reservation, returning quota capacity."""
        now_utc = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            UPDATE auto_draft_reservations
            SET status = 'released', released_at = ?, release_reason = ?
            WHERE reservation_id = ? AND status = 'active'
            """,
            (now_utc, reason, str(reservation_id)),
        )

    def count_reservations_for_run(self, run_id: uuid.UUID) -> int:
        """Count total document request units reserved for a logical evaluation run."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(SUM(document_units), 0)
            FROM auto_draft_reservations
            WHERE evaluation_run_id = ? AND status IN ('active', 'consumed')
            """,
            (str(run_id),),
        )
        return int(cursor.fetchone()[0])

    def count_reservations_in_window(
        self,
        candidate_id: uuid.UUID,
        org_id: str,
        since_utc: datetime,
    ) -> int:
        """Count total units reserved in a rolling window."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(SUM(document_units), 0)
            FROM auto_draft_reservations
            WHERE candidate_id = ? AND salesforce_org_id = ?
              AND status IN ('active', 'consumed')
              AND reserved_at >= ?
            """,
            (str(candidate_id), org_id, since_utc.isoformat()),
        )
        return int(cursor.fetchone()[0])

    def count_reservations_for_job(self, canonical_job_id: uuid.UUID) -> int:
        """Count total units reserved across time for a specific job."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(SUM(document_units), 0)
            FROM auto_draft_reservations
            WHERE canonical_job_id = ? AND status IN ('active', 'consumed')
            """,
            (str(canonical_job_id),),
        )
        return int(cursor.fetchone()[0])

    def count_outstanding_reservations(self, candidate_id: uuid.UUID, org_id: str) -> int:
        """Count total currently outstanding (uncompleted) automatic requests."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(SUM(r.document_units), 0)
            FROM auto_draft_reservations r
            JOIN auto_draft_intents i ON r.intent_id = i.intent_id
            WHERE r.candidate_id = ? AND r.salesforce_org_id = ?
              AND r.status = 'active'
              AND i.submission_state IN ('reserved', 'sending', 'uncertain', 'acknowledged')
            """,
            (str(candidate_id), org_id),
        )
        return int(cursor.fetchone()[0])

    # -------------------------------------------------------------------------
    # Request Bindings
    # -------------------------------------------------------------------------

    def save_binding(self, binding: AutomaticRequestBinding) -> None:
        """Persist a durable association between a C13 request and an automatic intent."""
        now_utc = datetime.now(timezone.utc).isoformat()
        receipt_json = json.dumps(binding.revalidation_receipt) if binding.revalidation_receipt else None
        self._execute(
            """
            INSERT INTO auto_draft_request_bindings (
                binding_id, local_request_id, intent_id, client_request_key,
                candidate_id, salesforce_org_id, canonical_job_id,
                policy_id, policy_version, policy_content_hash,
                expected_assessment_id, expected_assessment_fingerprint,
                expected_material_fingerprint, expected_posting_revision_hash,
                expected_profile_version, expected_profile_digest,
                expected_search_policy_version, expected_search_policy_hash,
                revalidation_receipt_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(binding.binding_id),
                str(binding.local_request_id),
                str(binding.intent_id),
                binding.client_request_key,
                str(binding.candidate_id),
                binding.salesforce_org_id,
                str(binding.canonical_job_id),
                binding.policy_id,
                binding.policy_version,
                binding.policy_content_hash,
                str(binding.expected_assessment_id),
                binding.expected_assessment_fingerprint,
                binding.expected_material_fingerprint,
                binding.expected_posting_revision_hash,
                binding.expected_profile_version,
                binding.expected_profile_digest,
                binding.expected_search_policy_version,
                binding.expected_search_policy_hash,
                receipt_json,
                now_utc,
            ),
        )

    def get_binding_by_request_id(self, local_request_id: uuid.UUID) -> AutomaticRequestBinding | None:
        """Retrieve binding for a local C13 GenerationRequest."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM auto_draft_request_bindings WHERE local_request_id = ?",
            (str(local_request_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_binding(cursor, row)

    def get_binding_by_intent_id(self, intent_id: uuid.UUID) -> AutomaticRequestBinding | None:
        """Retrieve binding for an automatic intent."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM auto_draft_request_bindings WHERE intent_id = ?",
            (str(intent_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_binding(cursor, row)

    def update_revalidation_receipt(self, binding_id: uuid.UUID, receipt: dict[str, Any]) -> None:
        """Update revalidation receipt upon successful freeze preflight recheck."""
        self._execute(
            """
            UPDATE auto_draft_request_bindings
            SET revalidation_receipt_json = ?
            WHERE binding_id = ?
            """,
            (json.dumps(receipt), str(binding_id)),
        )

    def _row_to_binding(self, cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> AutomaticRequestBinding:
        cols = [c[0] for c in cursor.description]
        d = dict(zip(cols, row))
        receipt = json.loads(d["revalidation_receipt_json"]) if d["revalidation_receipt_json"] else None
        return AutomaticRequestBinding(
            binding_id=uuid.UUID(d["binding_id"]),
            local_request_id=uuid.UUID(d["local_request_id"]),
            intent_id=uuid.UUID(d["intent_id"]),
            client_request_key=d["client_request_key"],
            candidate_id=uuid.UUID(d["candidate_id"]),
            salesforce_org_id=d["salesforce_org_id"],
            canonical_job_id=uuid.UUID(d["canonical_job_id"]),
            policy_id=d["policy_id"],
            policy_version=d["policy_version"],
            policy_content_hash=d["policy_content_hash"],
            expected_assessment_id=uuid.UUID(d["expected_assessment_id"]),
            expected_assessment_fingerprint=d["expected_assessment_fingerprint"],
            expected_material_fingerprint=d["expected_material_fingerprint"],
            expected_posting_revision_hash=d["expected_posting_revision_hash"],
            expected_profile_version=d["expected_profile_version"],
            expected_profile_digest=d["expected_profile_digest"],
            expected_search_policy_version=d["expected_search_policy_version"],
            expected_search_policy_hash=d["expected_search_policy_hash"],
            revalidation_receipt=receipt,
            created_at=datetime.fromisoformat(d["created_at"]),
        )

