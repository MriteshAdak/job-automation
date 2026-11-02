"""Tests for atomic transactions and clean rollback verification."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    PostingAvailability,
    SyncOperationState,
)
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.storage.connection import transaction
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import DuplicateKeyError


class TestTransactions:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "trans_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    def test_transaction_commit_success(self, engine: StorageEngine) -> None:
        run_id = uuid.uuid4()
        with engine.transaction() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, start_time, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(run_id),
                    datetime.now(timezone.utc).isoformat(),
                    "running",
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

        cur = engine.conn.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?", (str(run_id),))
        assert cur.fetchone()[0] == 1

    def test_transaction_rollback_on_exception(self, engine: StorageEngine) -> None:
        run_id = uuid.uuid4()
        with pytest.raises(RuntimeError, match="Simulated mid-transaction failure"):
            with engine.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, start_time, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(run_id),
                        datetime.now(timezone.utc).isoformat(),
                        "running",
                        datetime.now(timezone.utc).isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                # Verify row is visible within the uncommitted transaction
                cur = conn.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?", (str(run_id),))
                assert cur.fetchone()[0] == 1

                # Crash before completion
                raise RuntimeError("Simulated mid-transaction failure")

        # After rollback, row must NOT exist in the database
        cur = engine.conn.execute("SELECT COUNT(*) FROM runs WHERE run_id = ?", (str(run_id),))
        assert cur.fetchone()[0] == 0

    def test_atomic_commit_assessment_and_sync_success(self, engine: StorageEngine) -> None:
        # Create parent canonical job first for foreign key integrity
        job_id = uuid.uuid4()
        from job_automation.contracts.identity import CanonicalJob
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Test Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        assessment = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=job_id,
            posting_revision="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            profile_version="1.0",
            policy_version="1.0",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Meets all deterministic criteria",
        )

        payload = SyncPayload(
            canonical_job_id=job_id,
            job_title="Software Architect",
            company_name="Test Corp",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=AssessmentDisposition.ELIGIBLE,
            assessment_reasons="Meets criteria",
            last_evaluated_at=now_dt,
        )
        sync_op = SyncOperation(
            operation_id=uuid.uuid4(),
            canonical_job_id=job_id,
            payload_version="v1",
            payload_fingerprint="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            locally_owned_payload=payload,
            state=SyncOperationState.PENDING,
        )

        engine.sync_outbox.atomic_commit_assessment_and_sync(assessment, sync_op)

        # Both records must be present
        saved_asm = engine.assessments.get_assessment(assessment.assessment_id)
        saved_op = engine.sync_outbox.get_operation(sync_op.operation_id)
        assert saved_asm is not None
        assert saved_asm.assessment_id == assessment.assessment_id
        assert saved_op is not None
        assert saved_op.operation_id == sync_op.operation_id

    def test_atomic_commit_assessment_and_sync_rollback_on_conflict(
        self, engine: StorageEngine
    ) -> None:
        job_id = uuid.uuid4()
        from job_automation.contracts.identity import CanonicalJob
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Test Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        # Existing operation to trigger collision on sync_op
        existing_op_id = uuid.uuid4()
        payload = SyncPayload(
            canonical_job_id=job_id,
            job_title="Dev",
            company_name="Test Corp",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=AssessmentDisposition.ELIGIBLE,
            assessment_reasons="Existing",
            last_evaluated_at=now_dt,
        )
        existing_op = SyncOperation(
            operation_id=existing_op_id,
            canonical_job_id=job_id,
            payload_version="v1",
            payload_fingerprint="sha256:3333333333333333333333333333333333333333333333333333333333333333",
            locally_owned_payload=payload,
        )
        engine.sync_outbox.enqueue_operation(existing_op)

        # New assessment + conflicting sync_op (reuses existing_op_id)
        assessment_id = uuid.uuid4()
        assessment = Assessment(
            assessment_id=assessment_id,
            canonical_job_id=job_id,
            posting_revision="sha256:4444444444444444444444444444444444444444444444444444444444444444",
            profile_version="1.0",
            policy_version="1.0",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Meets criteria",
        )
        conflicting_op = SyncOperation(
            operation_id=existing_op_id,  # Duplicate!
            canonical_job_id=job_id,
            payload_version="v2",
            payload_fingerprint="sha256:5555555555555555555555555555555555555555555555555555555555555555",
            locally_owned_payload=payload,
        )

        with pytest.raises(DuplicateKeyError):
            engine.sync_outbox.atomic_commit_assessment_and_sync(assessment, conflicting_op)

        # Assessment MUST NOT be committed because sync_op failed!
        assert engine.assessments.get_assessment(assessment_id) is None

