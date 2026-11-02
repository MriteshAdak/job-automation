"""Immutable logical drafts and separate durable attempts; no physical artifacts."""
from __future__ import annotations

from job_automation.storage.connection import transaction
from job_automation.storage.repositories.base import BaseRepository
from job_automation.models.records import LogicalCallAuditRecord


def _digest(data):
    from job_automation.generation.input_records import compute_sha256_digest
    return compute_sha256_digest(data)


def _receipt_cls():
    from job_automation.generation.draft_records import DraftGenerationReceipt
    return DraftGenerationReceipt


class DraftContentRepository(BaseRepository):
    def start_attempt(self, receipt_id, request_id, logical_key, binding_hash, seal_id, context_id, started_at, call):
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO draft_content_attempts (attempt_id, request_id, logical_key, binding_hash, seal_id, context_receipt_id, started_at, call_json, call_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(receipt_id), str(request_id), logical_key, binding_hash, seal_id, str(context_id), started_at.isoformat(), call.model_dump_json(), str(call.call_id)),
            )

    def record_call(self, record: LogicalCallAuditRecord):
        """LLM-01 AuditRecorder port; one immutable audit per draft invocation."""
        with transaction(self.conn):
            self.conn.execute("INSERT INTO draft_model_audits (call_id, audit_json, audit_hash) VALUES (?, ?, ?)",
                              (str(record.call_id), record.model_dump_json(), _digest(record)))

    def get_call_audit(self, call_id):
        row = self.conn.execute("SELECT audit_json, audit_hash FROM draft_model_audits WHERE call_id=?", (str(call_id),)).fetchone()
        if row is None:
            raise ValueError("draft_audit_missing")
        record = LogicalCallAuditRecord.model_validate_json(row["audit_json"])
        if record.call_id != call_id or _digest(record) != row["audit_hash"]:
            raise ValueError("draft_audit_corrupt")
        return record

    def finish_attempt(self, receipt):
        with transaction(self.conn):
            cursor = self.conn.execute(
                "UPDATE draft_content_attempts SET receipt_json=?, receipt_hash=?, completed_at=? WHERE attempt_id=? AND receipt_json IS NULL",
                (receipt.model_dump_json(), _digest(receipt), receipt.completed_at.isoformat(), str(receipt.receipt_id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("draft_attempt_conflict")
            if receipt.draft is not None:
                self.conn.execute(
                    "INSERT INTO draft_content_results (request_id, logical_key, receipt_id) VALUES (?, ?, ?) ON CONFLICT(request_id) DO NOTHING",
                    (str(receipt.request_id), receipt.logical_key, str(receipt.receipt_id)),
                )
        # A concurrent matching first commit wins; caller verifies all bindings.
        return self.get_by_request(receipt.request_id) if receipt.draft else receipt

    def get_by_request(self, request_id):
        row = self.conn.execute("SELECT receipt_id FROM draft_content_results WHERE request_id=?", (str(request_id),)).fetchone()
        return self.reopen(row["receipt_id"]) if row else None

    def reopen(self, receipt_id):
        row = self.conn.execute("SELECT * FROM draft_content_attempts WHERE attempt_id=?", (str(receipt_id),)).fetchone()
        if row is None or row["receipt_json"] is None:
            raise ValueError("draft_receipt_missing")
        receipt_cls = _receipt_cls()
        result = receipt_cls.model_validate_json(row["receipt_json"])
        if (_digest(result) != row["receipt_hash"] or str(result.request_id) != row["request_id"]
                or str(result.receipt_id) != row["attempt_id"] or result.binding_hash != row["binding_hash"]
                or result.logical_key != row["logical_key"] or result.seal_id != row["seal_id"]
                or str(result.context_receipt_id) != row["context_receipt_id"]
                or result.call is None or str(result.call.call_id) != row["call_id"]
                or result.call.model_dump_json() != row["call_json"]):
            raise ValueError("draft_receipt_corrupt")
        if result.draft is not None and _digest(result.draft) != result.content_hash:
            raise ValueError("draft_content_corrupt")
        if result.draft is not None:
            self.get_call_audit(result.call.call_id)
            provenance = result.draft.provenance
            if (result.draft.request_id != result.request_id or provenance.receipt_id != result.receipt_id
                    or provenance.binding_hash != result.binding_hash or provenance.recipe_hash != result.recipe_hash
                    or provenance.model_call_ref != result.call.call_id):
                raise ValueError("draft_receipt_corrupt")
        return result
