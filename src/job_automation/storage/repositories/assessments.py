"""Job assessment repository."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from job_automation.contracts.assessment import Assessment
from job_automation.storage.exceptions import DuplicateKeyError
from job_automation.storage.repositories.base import BaseRepository


class AssessmentRepository(BaseRepository):
    """Manages C11 Assessment persistence."""

    def save_assessment(self, assessment: Assessment) -> None:
        """Persist a job assessment record.

        Raises DuplicateKeyError if an assessment with the same ID exists.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO assessments (
                        assessment_id, canonical_job_id, posting_revision,
                        profile_version, policy_version, assessment_method,
                        relevance_decision, relevance_score, final_disposition,
                        summary_reason, assessment_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(assessment.assessment_id),
                        str(assessment.canonical_job_id),
                        assessment.posting_revision,
                        assessment.profile_version,
                        assessment.policy_version,
                        assessment.assessment_method.value,
                        assessment.relevance_decision.value,
                        assessment.relevance_score,
                        assessment.final_disposition.value,
                        assessment.summary_reason,
                        assessment.model_dump_json(),
                        now_utc,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc) or "PRIMARY KEY" in str(exc):
                raise DuplicateKeyError(
                    f"Assessment with ID '{assessment.assessment_id}' already exists",
                    constraint="assessments_pk",
                ) from exc
            raise

    def get_assessment(self, assessment_id: uuid.UUID) -> Assessment | None:
        """Fetch assessment by UUID."""
        cursor = self.conn.execute(
            "SELECT assessment_json FROM assessments WHERE assessment_id = ?",
            (str(assessment_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Assessment.model_validate_json(row["assessment_json"])

    def get_assessments_for_job(self, canonical_job_id: uuid.UUID) -> list[Assessment]:
        """Fetch all assessments evaluated for a given canonical job."""
        cursor = self.conn.execute(
            "SELECT assessment_json FROM assessments WHERE canonical_job_id = ? ORDER BY created_at ASC",
            (str(canonical_job_id),),
        )
        return [
            Assessment.model_validate_json(row["assessment_json"])
            for row in cursor.fetchall()
        ]

    def get_latest_assessment(self, canonical_job_id: uuid.UUID) -> Assessment | None:
        """Fetch most recent assessment for a canonical job."""
        cursor = self.conn.execute(
            "SELECT assessment_json FROM assessments WHERE canonical_job_id = ? ORDER BY created_at DESC LIMIT 1",
            (str(canonical_job_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Assessment.model_validate_json(row["assessment_json"])

