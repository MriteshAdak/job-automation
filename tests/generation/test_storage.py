"""Tests for GEN-01 storage repositories, migrations, and atomic commit semantics."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.errors import FreezeConflictError
from job_automation.generation.records import (
    ArtifactDeliveryRecord,
    FreezeManifest,
    GenerationRequestObservation,
    ProjectionIntent,
    ProjectionStatus,
    StageAttempt,
    StageCheckpoint,
    StageStatus,
)
from job_automation.storage.connection import open_connection, transaction
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "gen_test.db"
    artifacts_dir = tmp_path / "artifacts"
    raw_dir = tmp_path / "raw"
    eng = StorageEngine(
        db_path=db_path,
        raw_dir=raw_dir,
        artifacts_dir=artifacts_dir,
    )
    eng.initialize_schema()
    return eng


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID) -> None:
    now_utc = datetime.now(timezone.utc)
    cjob = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp",
        availability=PostingAvailability.ACTIVE,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestGenerationStorage:
    def test_schema_migration_010_applied(self, engine: StorageEngine) -> None:
        version = engine.get_schema_version()
        assert version >= 10

    def test_observations_crud(self, engine: StorageEngine) -> None:
        obs_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        obs = GenerationRequestObservation(
            observation_id=obs_id,
            org_id="00D000000000001EAA",
            salesforce_request_id="a00123456789ABC",
            canonical_salesforce_id="a00123456789ABCAA2",
            client_request_key="client-123",
            remote_state="Pending",
            observed_at=now_utc,
            raw_record={"Id": "a00123456789ABC", "Status__c": "Pending"},
        )
        engine.generation_work.save_observation(obs)

        fetched = engine.generation_work.get_observation(obs_id)
        assert fetched is not None
        assert fetched.observation_id == obs_id
        assert fetched.canonical_salesforce_id == "a00123456789ABCAA2"

        by_sf = engine.generation_work.get_observation_by_salesforce_id(
            "00D000000000001EAA", "a00123456789ABCAA2"
        )
        assert by_sf is not None
        assert by_sf.observation_id == obs_id

    def test_atomic_commit_frozen_request_success(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)
        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)

        # 1. Create initial PENDING request
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00123456789ABCAA2",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="template_1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
        )
        engine.generation_requests.create_request(req)

        # 2. Prepare manifest, checkpoint, projection intent
        manifest = FreezeManifest(
            manifest_id=f"manifest:{req_id}",
            manifest_hash="sha256:" + "1" * 64,
            canonical_job_id=job_id,
            posting_revision_id="rev-1",
            posting_revision_hash="hash-1",
            profile_version="v1",
            policy_version="v1",
            template_id="template_1",
            template_version="t1",
            options_digest="sha256:" + "2" * 64,
            frozen_at=now_utc,
        )
        chk = StageCheckpoint(
            request_id=req_id,
            stage_name="freeze",
            stage_operation_id=f"freeze:{req_id}",
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=now_utc,
        )
        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker=f"op:{req_id}",
            desired_remote_state="Running",
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        claimed_req = req.model_copy(
            update={
                "state": GenerationProcessing.RUNNING,
                "claimed_at": now_utc,
                "frozen_input_versions": FrozenInputVersions(
                    posting_revision="hash-1",
                    profile_version="v1",
                    policy_version="v1",
                    template_version="t1",
                ),
            }
        )

        # 3. Commit atomically
        engine.generation_work.commit_frozen_request(
            request=claimed_req,
            manifest=manifest,
            checkpoint=chk,
            projection_intent=intent,
        )

        # 4. Verify all records persisted
        updated_req = engine.generation_requests.get_request(req_id)
        assert updated_req is not None
        assert updated_req.state == GenerationProcessing.RUNNING
        assert updated_req.frozen_input_versions is not None

        saved_freeze = engine.generation_work.get_freeze_association(req_id)
        assert saved_freeze is not None
        assert saved_freeze.manifest_hash == manifest.manifest_hash

        saved_chk = engine.generation_work.get_checkpoint(req_id, "freeze")
        assert saved_chk is not None
        assert saved_chk.status == StageStatus.COMPLETED

        saved_intent = engine.generation_work.get_projection_intent(req_id, 1)
        assert saved_intent is not None
        assert saved_intent.desired_remote_state == "Running"

    def test_atomic_commit_frozen_request_rollback_on_failure(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)
        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)

        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00123456789ABCAA2",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="template_1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
        )
        engine.generation_requests.create_request(req)

        manifest = FreezeManifest(
            manifest_id=f"manifest:{req_id}",
            manifest_hash="sha256:" + "1" * 64,
            canonical_job_id=job_id,
            posting_revision_id="rev-1",
            posting_revision_hash="hash-1",
            profile_version="v1",
            policy_version="v1",
            template_id="template_1",
            template_version="t1",
            options_digest="sha256:" + "2" * 64,
            frozen_at=now_utc,
        )
        chk = StageCheckpoint(
            request_id=req_id,
            stage_name="freeze",
            stage_operation_id=f"freeze:{req_id}",
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=now_utc,
        )
        # Create an intent that violates unique constraint by duplicating intent_id
        intent1 = ProjectionIntent(
            intent_id=uuid.uuid4(),
            request_id=req_id,
            projection_revision=1,
            operation_marker=f"op1:{req_id}",
            desired_remote_state="Running",
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        claimed_req = req.model_copy(
            update={
                "state": GenerationProcessing.RUNNING,
                "claimed_at": now_utc,
                "frozen_input_versions": FrozenInputVersions(
                    posting_revision="hash-1",
                    profile_version="v1",
                    policy_version="v1",
                    template_version="t1",
                ),
            }
        )

        # Inject failure by mocking or breaking transaction
        with pytest.raises(Exception):
            with transaction(engine.conn):
                engine.generation_work.commit_frozen_request(
                    request=claimed_req,
                    manifest=manifest,
                    checkpoint=chk,
                    projection_intent=intent1,
                )
                # Intentionally trigger an IntegrityError to force rollback
                engine.conn.execute("INSERT INTO generation_requests (request_id) VALUES (NULL)")

        # Verify rollback: request is still in PENDING state, no freeze association exists
        reloaded = engine.generation_requests.get_request(req_id)
        assert reloaded is not None
        assert reloaded.state == GenerationProcessing.PENDING
        assert reloaded.frozen_input_versions is None
        assert engine.generation_work.get_freeze_association(req_id) is None

    def test_re_freeze_conflict_rejected(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)
        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)

        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00123456789ABCAA2",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="template_1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
        )
        engine.generation_requests.create_request(req)

        manifest1 = FreezeManifest(
            manifest_id=f"manifest:{req_id}",
            manifest_hash="sha256:" + "1" * 64,
            canonical_job_id=job_id,
            posting_revision_id="rev-1",
            posting_revision_hash="hash-1",
            profile_version="v1",
            policy_version="v1",
            template_id="template_1",
            template_version="t1",
            options_digest="sha256:" + "2" * 64,
            frozen_at=now_utc,
        )
        chk = StageCheckpoint(
            request_id=req_id,
            stage_name="freeze",
            stage_operation_id=f"freeze:{req_id}",
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=now_utc,
        )
        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker=f"op:{req_id}",
            desired_remote_state="Running",
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        claimed_req = req.model_copy(
            update={
                "state": GenerationProcessing.RUNNING,
                "claimed_at": now_utc,
                "frozen_input_versions": FrozenInputVersions(
                    posting_revision="hash-1",
                    profile_version="v1",
                    policy_version="v1",
                    template_version="t1",
                ),
            }
        )

        engine.generation_work.commit_frozen_request(claimed_req, manifest1, chk, intent)

        # Attempt to freeze again with a different manifest hash
        manifest2 = manifest1.model_copy(update={"manifest_hash": "sha256:" + "9" * 64})
        with pytest.raises(FreezeConflictError, match="already frozen with different manifest"):
            engine.generation_work.commit_frozen_request(claimed_req, manifest2, chk, intent)

    def test_canonical_job_cascade_delete_protected_when_claimed(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)
        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)

        # Claimed running request
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00123456789ABCAA2",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="template_1",
            state=GenerationProcessing.RUNNING,
            created_at=now_utc,
            claimed_at=now_utc,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="hash-1",
                profile_version="v1",
                policy_version="v1",
                template_version="t1",
            ),
        )
        engine.generation_requests.create_request(req)

        # Attempting to delete canonical job must be aborted by trigger
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="Cannot delete canonical job referenced by claimed generation request"):
            engine.conn.execute("DELETE FROM canonical_jobs WHERE canonical_job_id = ?", (str(job_id),))
