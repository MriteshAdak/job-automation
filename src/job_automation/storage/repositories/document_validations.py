"""Durable document validation attempts and logical results repository (GEN-04-S06)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from job_automation.generation.validation_records import (
    DocumentValidationReport,
    compute_report_hash,
)
from job_automation.storage.connection import transaction
from job_automation.storage.repositories.base import BaseRepository


class DocumentValidationRepository(BaseRepository):
    """Repository managing document validation attempts and CAS result commitments."""

    def start_attempt(
        self,
        attempt_id: uuid.UUID,
        request_id: uuid.UUID,
        logical_key: str,
        binding_hash: str,
        draft_receipt_id: uuid.UUID,
        draft_hash: str,
        rule_set_id: str,
        started_at: datetime,
    ) -> None:
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO document_validation_attempts (
                    attempt_id, request_id, logical_key, binding_hash,
                    draft_receipt_id, draft_hash, rule_set_id, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(attempt_id),
                    str(request_id),
                    logical_key,
                    binding_hash,
                    str(draft_receipt_id),
                    draft_hash,
                    rule_set_id,
                    started_at.isoformat(),
                ),
            )

    def finish_attempt(
        self,
        attempt_id: uuid.UUID,
        report: DocumentValidationReport,
    ) -> DocumentValidationReport:
        with transaction(self.conn):
            cursor = self.conn.execute(
                """
                UPDATE document_validation_attempts
                SET completed_at = ?, report_json = ?, report_hash = ?,
                    fatal_count = ?, warning_count = ?, render_decision = ?
                WHERE attempt_id = ? AND report_json IS NULL
                """,
                (
                    report.completed_at.isoformat(),
                    report.model_dump_json(),
                    report.report_hash,
                    report.fatal_count,
                    report.warning_count,
                    report.render_decision,
                    str(attempt_id),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("validation_attempt_conflict")

            self.conn.execute(
                """
                INSERT INTO document_validation_results (
                    request_id, logical_key, attempt_id, report_hash, render_decision
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO NOTHING
                """,
                (
                    str(report.request_id),
                    report.input_binding.rule_set_digest,
                    str(attempt_id),
                    report.report_hash,
                    report.render_decision,
                ),
            )

        # Return the winning committed report for this request
        return self.get_by_request(report.request_id) or report

    def get_by_request(self, request_id: uuid.UUID) -> DocumentValidationReport | None:
        row = self.conn.execute(
            "SELECT attempt_id FROM document_validation_results WHERE request_id = ?",
            (str(request_id),),
        ).fetchone()
        return self.reopen(uuid.UUID(row["attempt_id"])) if row else None

    def reopen(self, attempt_id: uuid.UUID) -> DocumentValidationReport:
        row = self.conn.execute(
            "SELECT * FROM document_validation_attempts WHERE attempt_id = ?",
            (str(attempt_id),),
        ).fetchone()
        if row is None or row["report_json"] is None:
            raise ValueError("validation_report_missing")

        report = DocumentValidationReport.model_validate_json(row["report_json"])
        recomputed_hash = compute_report_hash(json.loads(row["report_json"]))

        if (
            recomputed_hash != row["report_hash"]
            or report.report_hash != row["report_hash"]
            or str(report.report_id) != row["attempt_id"]
            or str(report.request_id) != row["request_id"]
            or report.input_binding.binding_hash != row["binding_hash"]
            or report.validated_draft_hash != row["draft_hash"]
            or report.rule_set_id != row["rule_set_id"]
            or report.fatal_count != row["fatal_count"]
            or report.warning_count != row["warning_count"]
            or report.render_decision != row["render_decision"]
        ):
            raise ValueError("validation_report_corrupt")

        return report

