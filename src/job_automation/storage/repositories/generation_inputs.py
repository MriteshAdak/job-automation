"""Storage repository for GEN-02 frozen seals, component snapshots, and preflight receipts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.errors import ClassifiedError
from job_automation.generation.errors import FreezeConflictError
from job_automation.generation.input_errors import frozen_input_corrupt_error
from job_automation.storage.connection import _TRANSACTION_DEPTHS, transaction
from job_automation.storage.exceptions import DuplicateKeyError, StorageError
from job_automation.storage.repositories.base import BaseRepository

if TYPE_CHECKING:
    from job_automation.generation.input_records import (
        FrozenContextReceipt,
        FrozenSeal,
        PreflightReceipt,
    )


class GenerationInputRepository(BaseRepository):
    """Manages persistence, integrity verification, and retrieval of frozen input seals and receipts."""

    def _execute(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        """Execute a statement safely, respecting outer transactions if active."""
        depth = _TRANSACTION_DEPTHS.get(id(self.conn), 0)
        if depth > 0:
            return self.conn.execute(sql, params)
        with self.conn:
            return self.conn.execute(sql, params)

    # -------------------------------------------------------------------------
    # Preflight Receipts
    # -------------------------------------------------------------------------

    def save_preflight_receipt(self, receipt: PreflightReceipt) -> None:
        """Persist or update a preflight audit receipt."""
        now_utc = datetime.now(timezone.utc).isoformat()
        err_json = receipt.error.model_dump_json() if receipt.error else None
        self._execute(
            """
            INSERT INTO generation_preflight_receipts (
                receipt_id, request_id, freeze_op_id, accepted_options_digest,
                result, seal_id, seal_hash, warnings_json, error_json,
                reason_code, started_at, completed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(receipt_id) DO UPDATE SET
                result = excluded.result,
                seal_id = excluded.seal_id,
                seal_hash = excluded.seal_hash,
                warnings_json = excluded.warnings_json,
                error_json = excluded.error_json,
                reason_code = excluded.reason_code,
                completed_at = excluded.completed_at
            """,
            (
                str(receipt.receipt_id),
                str(receipt.request_id),
                receipt.freeze_op_id,
                receipt.accepted_options_digest,
                receipt.result,
                receipt.seal_id,
                receipt.seal_hash,
                json.dumps(receipt.warnings),
                err_json,
                receipt.reason_code,
                receipt.started_at.isoformat(),
                receipt.completed_at.isoformat(),
                now_utc,
            ),
        )

    def get_preflight_receipt(self, request_id: uuid.UUID) -> PreflightReceipt | None:
        """Retrieve most recent preflight receipt for a generation request."""
        cursor = self.conn.execute(
            """
            SELECT receipt_id, request_id, freeze_op_id, accepted_options_digest,
                   result, seal_id, seal_hash, warnings_json, error_json,
                   reason_code, started_at, completed_at
            FROM generation_preflight_receipts
            WHERE request_id = ?
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (str(request_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_preflight_receipt(row)

    def list_preflight_receipts(self, limit: int = 50) -> list[PreflightReceipt]:
        """List recent preflight receipts."""
        cursor = self.conn.execute(
            """
            SELECT receipt_id, request_id, freeze_op_id, accepted_options_digest,
                   result, seal_id, seal_hash, warnings_json, error_json,
                   reason_code, started_at, completed_at
            FROM generation_preflight_receipts
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_preflight_receipt(r) for r in cursor.fetchall()]

    def _row_to_preflight_receipt(self, row: sqlite3.Row) -> PreflightReceipt:
        from job_automation.generation.input_records import PreflightReceipt

        err = ClassifiedError.model_validate_json(row["error_json"]) if row["error_json"] else None
        return PreflightReceipt(
            receipt_id=uuid.UUID(row["receipt_id"]),
            request_id=uuid.UUID(row["request_id"]),
            freeze_op_id=row["freeze_op_id"],
            accepted_options_digest=row["accepted_options_digest"],
            result=row["result"],
            seal_id=row["seal_id"],
            seal_hash=row["seal_hash"],
            warnings=json.loads(row["warnings_json"]) if row["warnings_json"] else [],
            error=err,
            reason_code=row["reason_code"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]),
        )

    # -------------------------------------------------------------------------
    # Frozen Seals & Component Snapshots
    # -------------------------------------------------------------------------

    def save_seal(self, seal: FrozenSeal) -> None:
        """Atomically persist a complete FrozenSeal and its component snapshot bodies."""
        now_utc = datetime.now(timezone.utc).isoformat()

        with transaction(self.conn):
            # Check existing seal for this request
            cursor = self.conn.execute(
                "SELECT seal_id, manifest_hash, options_digest, seal_hash FROM generation_frozen_seals WHERE request_id = ?",
                (str(seal.request_id),),
            )
            existing = cursor.fetchone()
            if existing:
                if (
                    existing["seal_hash"] != seal.seal_hash
                    or existing["options_digest"] != seal.options.options_digest
                ):
                    raise FreezeConflictError(
                        f"Request {seal.request_id} is already sealed with different manifest or options "
                        f"(existing: {existing['seal_hash']}, new: {seal.seal_hash})"
                    )
                # Idempotent re-save of exact same seal
                return

            # Insert seal row
            self.conn.execute(
                """
                INSERT INTO generation_frozen_seals (
                    seal_id, request_id, manifest_id, manifest_hash, options_digest,
                    canonical_job_id, posting_revision_id, posting_revision_hash,
                    profile_version, policy_version, template_id, template_version,
                    context_strategy, target_language, availability_status,
                    allow_unavailable_job, frozen_at, seal_hash, seal_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seal.seal_id,
                    str(seal.request_id),
                    seal.manifest.manifest_id,
                    seal.manifest.manifest_hash,
                    seal.options.options_digest,
                    str(seal.canonical_job_id),
                    seal.manifest.posting_revision_id,
                    seal.manifest.posting_revision_hash,
                    seal.manifest.profile_version,
                    seal.manifest.policy_version,
                    seal.manifest.template_id,
                    seal.manifest.template_version,
                    seal.manifest.context_strategy.value,
                    seal.manifest.target_language,
                    seal.manifest.availability_status,
                    1 if seal.manifest.allow_unavailable_job else 0,
                    seal.sealed_at.isoformat(),
                    seal.seal_hash,
                    seal.model_dump_json(),
                    now_utc,
                ),
            )

            # Insert component snapshot bodies
            snapshots = [
                ("job", seal.job_snapshot.snapshot_digest, seal.job_snapshot.model_dump_json()),
                ("profile", seal.profile_snapshot.snapshot_digest, seal.profile_snapshot.model_dump_json()),
                ("options", seal.options.options_digest, seal.options.model_dump_json()),
                ("availability", seal.availability_check.check_digest, seal.availability_check.model_dump_json()),
                ("recipe", seal.recipe.recipe_digest, seal.recipe.model_dump_json()),
            ]

            for kind, digest, body_json in snapshots:
                snap_id = f"{seal.seal_id}:{kind}"
                self.conn.execute(
                    """
                    INSERT INTO generation_frozen_snapshots (
                        snapshot_id, seal_id, kind, snapshot_digest, snapshot_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(seal_id, kind) DO UPDATE SET
                        snapshot_digest = excluded.snapshot_digest,
                        snapshot_json = excluded.snapshot_json
                    """,
                    (snap_id, seal.seal_id, kind, digest, body_json, now_utc),
                )

    def get_seal_by_request_id(self, request_id: uuid.UUID) -> FrozenSeal | None:
        """Retrieve and integrity-check FrozenSeal by request UUID."""
        cursor = self.conn.execute(
            "SELECT seal_hash, seal_json FROM generation_frozen_seals WHERE request_id = ?",
            (str(request_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._validate_and_parse_seal(row)

    def get_seal_by_manifest_id(self, manifest_id: str) -> FrozenSeal | None:
        """Retrieve and integrity-check FrozenSeal by manifest ID."""
        cursor = self.conn.execute(
            "SELECT seal_hash, seal_json FROM generation_frozen_seals WHERE manifest_id = ?",
            (manifest_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._validate_and_parse_seal(row)

    def _validate_and_parse_seal(self, row: sqlite3.Row) -> FrozenSeal:
        from job_automation.generation.input_records import FrozenSeal

        seal_json = row["seal_json"]
        expected_hash = row["seal_hash"]
        seal = FrozenSeal.model_validate_json(seal_json)
        if seal.seal_hash != expected_hash:
            raise StorageError(f"Seal hash mismatch for seal {seal.seal_id}")
        return seal

    # -------------------------------------------------------------------------
    # Context Receipts
    # -------------------------------------------------------------------------

    def save_context_receipt(self, receipt: FrozenContextReceipt) -> None:
        """Atomically persist a complete FrozenContextReceipt."""
        now_utc = datetime.now(timezone.utc).isoformat()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO generation_context_receipts (
                    receipt_id, request_id, manifest_id, manifest_hash,
                    recipe_hash, context_op_id, result_hash, warnings_json,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id, result_hash) DO UPDATE SET
                    context_op_id = excluded.context_op_id,
                    warnings_json = excluded.warnings_json,
                    result_json = excluded.result_json
                """,
                (
                    str(receipt.receipt_id),
                    str(receipt.request_id),
                    receipt.manifest_id,
                    receipt.manifest_hash,
                    receipt.recipe_hash,
                    receipt.context_op_id,
                    receipt.result_hash,
                    json.dumps(receipt.warnings),
                    receipt.result.model_dump_json(),
                    now_utc,
                ),
            )

    def get_context_receipt(self, receipt_id: uuid.UUID) -> FrozenContextReceipt | None:
        """Retrieve a context receipt by UUID."""
        cursor = self.conn.execute(
            """
            SELECT receipt_id, request_id, manifest_id, manifest_hash,
                   recipe_hash, context_op_id, result_hash, warnings_json,
                   result_json, created_at
            FROM generation_context_receipts
            WHERE receipt_id = ?
            """,
            (str(receipt_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_context_receipt(row)

    def get_context_receipt_by_request_id(self, request_id: uuid.UUID) -> FrozenContextReceipt | None:
        """Retrieve most recent context receipt for a request."""
        cursor = self.conn.execute(
            """
            SELECT receipt_id, request_id, manifest_id, manifest_hash,
                   recipe_hash, context_op_id, result_hash, warnings_json,
                   result_json, created_at
            FROM generation_context_receipts
            WHERE request_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(request_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_context_receipt(row)

    def get_context_receipt_by_manifest_and_recipe(
        self, manifest_hash: str, recipe_hash: str
    ) -> FrozenContextReceipt | None:
        """Retrieve context receipt matching exact manifest and recipe hashes."""
        cursor = self.conn.execute(
            """
            SELECT receipt_id, request_id, manifest_id, manifest_hash,
                   recipe_hash, context_op_id, result_hash, warnings_json,
                   result_json, created_at
            FROM generation_context_receipts
            WHERE manifest_hash = ? AND recipe_hash = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (manifest_hash, recipe_hash),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_context_receipt(row)

    def list_context_receipts(self, limit: int = 50) -> list[FrozenContextReceipt]:
        """List recent context receipts."""
        cursor = self.conn.execute(
            """
            SELECT receipt_id, request_id, manifest_id, manifest_hash,
                   recipe_hash, context_op_id, result_hash, warnings_json,
                   result_json, created_at
            FROM generation_context_receipts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_context_receipt(r) for r in cursor.fetchall()]

    def _row_to_context_receipt(self, row: sqlite3.Row) -> FrozenContextReceipt:
        from job_automation.context.selector_records import ContextSelectionResult
        from job_automation.generation.input_records import FrozenContextReceipt

        res = ContextSelectionResult.model_validate_json(row["result_json"])
        return FrozenContextReceipt(
            receipt_id=uuid.UUID(row["receipt_id"]),
            request_id=uuid.UUID(row["request_id"]),
            manifest_id=row["manifest_id"],
            manifest_hash=row["manifest_hash"],
            recipe_hash=row["recipe_hash"],
            context_op_id=row["context_op_id"],
            result=res,
            warnings=json.loads(row["warnings_json"]) if row["warnings_json"] else [],
            result_hash=row["result_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
