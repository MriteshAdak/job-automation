"""Tests verifying absolute prevention of Salesforce publication side effects (EVAL-01-S03)."""

from pathlib import Path
import pytest

from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.errors import PublicationAttemptBlockedError
from job_automation.evaluation.ports import assert_no_publication_authority
from job_automation.evaluation.settings import EvaluationSettings
from job_automation.storage.engine import StorageEngine


def test_composition_rejects_enable_sync(tmp_path: Path):
    """Verify create_evaluation_environment refuses to start if enable_sync is True."""
    eval_dir = (tmp_path / "eval_workspace").resolve()
    # Pydantic model validator prevents constructing settings with enable_sync=True
    with pytest.raises(ValueError, match="enable_sync=True is strictly forbidden"):
        EvaluationSettings(
            eval_root=str(eval_dir),
            enable_sync=True,
        )


def test_assert_no_publication_authority_blocks_salesforce_objects():
    """Verify assert_no_publication_authority triggers on sync/salesforce objects."""
    class MaliciousObject:
        salesforce_gateway = "fake_gateway"

    with pytest.raises(PublicationAttemptBlockedError, match="unauthorized publication attribute"):
        assert_no_publication_authority(MaliciousObject())

    class SyncObject:
        sync_service = "fake_sync"

    with pytest.raises(PublicationAttemptBlockedError, match="unauthorized publication attribute"):
        assert_no_publication_authority(SyncObject())


def test_evaluation_leaves_production_outbox_untouched(tmp_path: Path):
    """Verify evaluation environment leaves existing production outbox and assessment rows completely untouched."""
    prod_db = tmp_path / "production.db"
    prod_engine = StorageEngine(
        db_path=prod_db,
        raw_dir=tmp_path / "raw",
        artifacts_dir=tmp_path / "artifacts",
    )
    prod_engine.migrate()

    # Insert a dummy pending outbox operation in production
    import uuid
    from datetime import datetime, timezone
    op_id = uuid.uuid4()
    can_id = uuid.uuid4()
    now_iso = datetime.now(timezone.utc).isoformat()
    prod_engine.conn.execute(
        """
        INSERT INTO canonical_jobs (
            canonical_job_id, company_name, availability, current_revision_id,
            first_seen_at, last_seen_at, job_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(can_id),
            "Test Company",
            "active",
            "rev1",
            now_iso,
            now_iso,
            "{}",
            now_iso,
            now_iso,
        ),
    )
    prod_engine.conn.execute(
        """
        INSERT INTO sync_operations (
            operation_id, canonical_job_id, payload_version, payload_fingerprint,
            state, attempt_count, max_attempts, payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(op_id),
            str(can_id),
            "1.0",
            "fp_test",
            "pending",
            0,
            3,
            '{"title": "Test Job"}',
            now_iso,
            now_iso,
        ),
    )
    prod_engine.conn.commit()

    # Now create evaluation environment
    eval_dir = (tmp_path / "eval_workspace").resolve()
    settings = EvaluationSettings(
        eval_root=str(eval_dir),
        production_db_path=str(prod_db),
    )
    env = create_evaluation_environment(settings)

    try:
        # Check production outbox is still pending and unchanged
        cursor = prod_engine.conn.execute(
            "SELECT state, attempt_count FROM sync_operations WHERE operation_id = ?",
            (str(op_id),),
        )
        row = cursor.fetchone()
        assert row["state"] == "pending"
        assert row["attempt_count"] == 0
    finally:
        env.close()
        prod_engine.close()
