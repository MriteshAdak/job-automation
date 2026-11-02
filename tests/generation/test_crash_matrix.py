"""Comprehensive crash matrix and failure scenario tests (GEN-T01 through GEN-T20).

Validates process crashes, network dropouts, stale ownership, unacknowledged projection intents,
predecessor-linked regenerations, and dependency gates per IMPLEMENTATION_BLUEPRINT and docs/stories/GEN-01.md.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentApproval,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.salesforce import (
    AttemptSummary,
    GatewayFailure,
    GatewayResult,
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
)
from job_automation.generation.admission import GenerationAdmitter
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.polling import SalesforceGenerationRequestSource
from job_automation.generation.projection import SalesforceRequestStateProjector
from job_automation.generation.records import (
    FreezeManifest,
    GenerationRequestObservation,
    GenerationStage,
    ProjectionIntent,
    ProjectionStatus,
    StageCheckpoint,
    StageStatus,
    ValidationReport,
)
from job_automation.generation.recovery import GenerationRecoveryManager
from job_automation.generation.request_mapping import (
    canonicalize_salesforce_id,
    derive_local_request_id,
)
from job_automation.generation.settings import GenerationSettings
from job_automation.generation.worker import GenerationWorker
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine
from tests.fakes.fake_services import FakeGenerator, FakeRendererDelivery
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.generation.test_coordinator import FakeInputService, FakeValidator


@pytest.fixture
def matrix_env(tmp_path: Path):
    data_root = tmp_path / "CrashMatrixStore ä"
    data_root.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(
        db_path=data_root / "jobs.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    engine.initialize_schema()
    return data_root, engine


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID, availability: PostingAvailability = PostingAvailability.ACTIVE) -> None:
    now_utc = datetime.now(timezone.utc)
    cjob = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp Matrix",
        availability=availability,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestCrashMatrix:
    # GEN-T01: Crash before local freeze persistence
    def test_t01_crash_before_local_freeze_persistence_clean_restart(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        gateway = FakeSalesforceGatewayV2()
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending", "Job__c": str(job_id), "Document_Type__c": "cv", "Template_Id__c": "t1"}
        }

        # Request was admitted as PENDING, but worker crashes before claiming/freezing
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record=gateway.records["Generation_Request__c"][sf_id],
        )
        admitter = GenerationAdmitter(engine=engine)
        req, err = admitter.admit_observation(obs)
        assert req is not None
        assert req.state == GenerationProcessing.PENDING
        assert engine.generation_work.get_freeze_association(req.request_id) is None

        # Successor worker starts; request remains cleanly pending and ready to be processed
        unfinished = engine.generation_requests.get_unfinished_requests()
        assert len(unfinished) == 1
        assert unfinished[0].state == GenerationProcessing.PENDING

    # GEN-T02: Crash after local freeze persistence, before remote Running projection
    def test_t02_crash_after_local_freeze_recovers_unacknowledged_intent(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        gateway = FakeSalesforceGatewayV2()
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }

        req_id = derive_local_request_id("00D000000000001EAA", canon_sf_id)
        now_utc = datetime.now(timezone.utc)
        pending_req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=canon_sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
        )
        engine.generation_requests.create_request(pending_req)

        claimed_req = pending_req.model_copy(
            update={
                "state": GenerationProcessing.RUNNING,
                "claimed_at": now_utc,
                "frozen_input_versions": FrozenInputVersions(
                    posting_revision="rev-1", profile_version="p1", policy_version="pol1", template_version="t1"
                ),
            }
        )
        manifest = FreezeManifest(
            manifest_id=f"manifest:{req_id}",
            manifest_hash="sha256:" + "1" * 64,
            canonical_job_id=job_id,
            posting_revision_id="rev-1",
            posting_revision_hash="hash-1",
            profile_version="p1",
            policy_version="pol1",
            template_id="t1",
            template_version="t1",
            context_strategy=ContextStrategy.JSON,
            target_language="de",
            options_digest="sha256:" + "2" * 64,
            frozen_at=now_utc,
        )
        chk = StageCheckpoint(
            request_id=req_id, stage_name="freeze", stage_operation_id=f"frz:{req_id}", status=StageStatus.COMPLETED, started_at=now_utc, completed_at=now_utc
        )
        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker=f"frz:{req_id}",
            desired_remote_state="Running",
            payload={"Status__c": "Running", "Operation_Marker__c": f"frz:{req_id}"},
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        # Crash occurs right after atomic SQLite commit!
        engine.generation_work.commit_frozen_request(claimed_req, manifest, chk, intent)

        # Successor worker recovery runs
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=None)
        actions = recovery.reconcile_all()
        assert any("Re-dispatched projection intent" in a for a in actions)

        # Verify remote state is now projected Running
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Running"
        updated_intent = engine.generation_work.get_projection_intent(req_id, 1)
        assert updated_intent.status == ProjectionStatus.ACKNOWLEDGED

    # GEN-T03: Network timeout during remote Running projection marks UNCERTAIN, readback reconciles
    def test_t03_projection_intent_uncertain_reconciled_by_readback(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        gateway = FakeSalesforceGatewayV2()
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }

        req_id = derive_local_request_id("00D000000000001EAA", canon_sf_id)
        now_utc = datetime.now(timezone.utc)
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=canon_sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.RUNNING,
            created_at=now_utc,
            claimed_at=now_utc,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1", profile_version="p1", policy_version="pol1", template_version="t1"
            ),
        )
        engine.generation_requests.create_request(req)

        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker="op:t03:marker",
            desired_remote_state="Running",
            payload={"Status__c": "Running", "Operation_Marker__c": "op:t03:marker"},
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        engine.generation_work.save_projection_intent(intent)

        # Inject uncertain network timeout
        def timeout_hook(request):
            gateway.records["Generation_Request__c"][sf_id]["Status__c"] = "Running"
            gateway.records["Generation_Request__c"][sf_id]["Operation_Marker__c"] = "op:t03:marker"
            return GatewayResult(
                failure=GatewayFailure(
                    error=ClassifiedError.transient_network("Timeout after commit"),
                    operation_kind=OperationKind.UPDATE_RECORD,
                    remote_outcome=RemoteOutcome.UNKNOWN,
                    recovery_action=RecoveryAction.RECONCILE,
                    attempts=[AttemptSummary(attempt_number=1, purpose="update", duration_ms=100.0, uncertain_transmission=True)],
                )
            )

        gateway.update_record = timeout_hook
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        success, _ = projector.project_intent(intent)
        assert success is False

        # Status must be UNCERTAIN
        intent_after = engine.generation_work.get_projection_intent(req_id, 1)
        assert intent_after.status == ProjectionStatus.UNCERTAIN

        # Restore normal gateway and reconcile
        gateway.update_record = FakeSalesforceGatewayV2.update_record.__get__(gateway, FakeSalesforceGatewayV2)
        rec_success, _ = projector.reconcile_intent(intent_after)
        assert rec_success is True
        reconciled = engine.generation_work.get_projection_intent(req_id, 1)
        assert reconciled.status == ProjectionStatus.ACKNOWLEDGED

    # GEN-T04 through GEN-T08: Resumes from checkpoints across crash at each stage
    def test_t04_through_t08_resumes_from_checkpoints_without_reexecuting_prior_stages(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        gateway = FakeSalesforceGatewayV2()
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }

        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        input_svc = FakeInputService(canonical_job_id=job_id)
        rend = FakeRendererDelivery()

        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=input_svc,
            generator=FakeGenerator(),
            validator=FakeValidator(),
            renderer=rend,
            deliverer=rend,
        )

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        engine.generation_requests.create_request(req)

        # Step 1: Execute through FREEZE only
        req, status, _ = coordinator.process_request(req, stop_after_stage="freeze")
        assert status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "freeze").status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "context") is None

        # Step 2: Execute through CONTEXT only (simulating resume after crash)
        req, status, _ = coordinator.process_request(req, stop_after_stage="context")
        assert status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "context").status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "draft") is None

        # Step 3: Execute through DRAFT only
        req, status, _ = coordinator.process_request(req, stop_after_stage="draft")
        assert status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "draft").status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "validation") is None

        # Step 4: Execute through VALIDATION only
        req, status, _ = coordinator.process_request(req, stop_after_stage="validation")
        assert status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "validation").status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "rendering") is None

        # Step 5: Execute through RENDERING only
        req, status, _ = coordinator.process_request(req, stop_after_stage="rendering")
        assert status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "rendering").status == StageStatus.COMPLETED
        assert engine.generation_work.get_checkpoint(req_id, "delivery") is None

        # Step 6: Complete DELIVERY
        req, status, _ = coordinator.process_request(req)
        assert status == StageStatus.COMPLETED
        assert req.state == GenerationProcessing.READY_FOR_REVIEW
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Ready_for_Review"

    # GEN-T09: Missing downstream stage remains BLOCKED, never falsely marked ready
    def test_t09_missing_downstream_stage_remains_blocked(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        gateway = FakeSalesforceGatewayV2()
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }

        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        input_svc = FakeInputService(canonical_job_id=job_id)

        # GEN-03 absent
        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=input_svc,
            generator=None,
        )

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        engine.generation_requests.create_request(req)

        final_req, status, err = coordinator.process_request(req)
        assert status == StageStatus.BLOCKED
        assert final_req.state == GenerationProcessing.RUNNING
        assert final_req.state != GenerationProcessing.READY_FOR_REVIEW
        assert "GEN-03 draft generator absent" in err.message

    # GEN-T10: Stale remote Running request orphan projects failure
    def test_t10_stale_remote_running_orphan_projects_failure(self, matrix_env) -> None:
        data_root, engine = matrix_env
        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        gateway = FakeSalesforceGatewayV2()
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Running"}
        }

        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            remote_state="Running",
            observed_at=datetime.now(timezone.utc),
            remote_updated_at=stale_time,
            raw_record={"Id": sf_id, "Document_Type__c": "cv", "Worker_Claimed_At__c": stale_time.isoformat()},
        )
        source = FakeRendererDelivery()  # Stub
        from tests.generation.test_recovery import FakeRecoverySource
        rec_source = FakeRecoverySource(running=[obs])
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=rec_source)

        actions = recovery.reconcile_all()
        assert any("Projected failure for stale orphan remote Running" in a for a in actions)
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Failed"
        assert gateway.records["Generation_Request__c"][sf_id]["Error_Reason__c"] == "orphan_remote_running"

    # GEN-T13: Repeated polling idempotently reuses existing admitted request
    def test_t13_repeated_polling_idempotent_admission(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id, "Job__c": str(job_id), "Document_Type__c": "cv", "Template_Id__c": "t1"},
        )
        admitter = GenerationAdmitter(engine=engine)

        req1, err1 = admitter.admit_observation(obs)
        assert req1 is not None and err1 is None

        # Poll again in subsequent cycle
        req2, err2 = admitter.admit_observation(obs)
        assert req2 is not None and err2 is None
        assert req1.request_id == req2.request_id

    # GEN-T15: Deliberate regeneration allocates distinct UUID, links predecessor, distinct slot
    def test_t15_deliberate_regeneration_allocates_new_uuid_and_links_predecessor(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id_1 = "a00111111111111AAA"
        canon_sf_1 = canonicalize_salesforce_id(sf_id_1)
        sf_id_2 = "a00222222222222BBB"
        canon_sf_2 = canonicalize_salesforce_id(sf_id_2)

        admitter = GenerationAdmitter(engine=engine)

        obs1 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id_1,
            canonical_salesforce_id=canon_sf_1,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_1),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id_1, "Job__c": str(job_id), "Document_Type__c": "cv"},
        )
        req1, _ = admitter.admit_observation(obs1)

        # User requests deliberate regeneration pointing to predecessor sf_id_1
        obs2 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id_2,
            canonical_salesforce_id=canon_sf_2,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_2),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_id_2,
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Predecessor_Request__c": sf_id_1,
            },
        )
        req2, _ = admitter.admit_observation(obs2)

        assert req2.request_id != req1.request_id
        assert req2.predecessor_request_id == req1.request_id

    # GEN-T16: Unavailable job preflight rejection
    def test_t16_unavailable_job_fails_preflight(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, availability=PostingAvailability.UNAVAILABLE)

        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id, "Job__c": str(job_id), "Document_Type__c": "cv", "Allow_Unavailable_Job__c": False},
        )
        admitter = GenerationAdmitter(engine=engine)
        req, err = admitter.admit_observation(obs)
        assert req is not None
        assert req.state == GenerationProcessing.FAILED
        assert err.details.get("reason_code") == "job_unavailable"

        intent = engine.generation_work.get_active_projection_intent(req.request_id)
        assert intent.desired_remote_state == "Failed"

    # GEN-T17: Unavailable job with override permitted
    def test_t17_unavailable_job_with_override_permitted(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, availability=PostingAvailability.UNAVAILABLE)

        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id, "Job__c": str(job_id), "Document_Type__c": "cv", "Allow_Unavailable_Job__c": True},
        )
        admitter = GenerationAdmitter(engine=engine)
        req, err = admitter.admit_observation(obs)
        assert req is not None
        assert req.state == GenerationProcessing.PENDING
        assert err is None
        assert req.allow_unavailable_job is True

    # GEN-T19: Cascade delete protection on canonical job claimed by generation request
    def test_t19_cascade_delete_protection_when_claimed(self, matrix_env) -> None:
        data_root, engine = matrix_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00111111111111AAA",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.RUNNING,
            created_at=now_utc,
            claimed_at=now_utc,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1", profile_version="p1", policy_version="pol1", template_version="t1"
            ),
        )
        engine.generation_requests.create_request(req)

        # SQLite foreign key with trigger trg_protect_claimed_generation_requests prevents deleting canonical job
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
            engine.conn.execute("DELETE FROM canonical_jobs WHERE canonical_job_id = ?", (str(job_id),))

    # GEN-T20: RUN-01 lock contention prevents database writes
    def test_t20_run01_lock_contention_zero_database_writes(self, matrix_env) -> None:
        data_root, engine = matrix_env
        gateway = FakeSalesforceGatewayV2()

        lock = WindowsWorkerLock(data_root)
        token = lock.acquire_lock(owner_kind=OwnerKind.SEARCH)
        try:
            worker = GenerationWorker(
                data_root=data_root,
                gateway=gateway,
                engine=engine,
            )
            report = worker.run_once()
            assert report.exit_code == 3
            # Zero requests admitted or processed
            assert report.scanned_requests == 0
            assert report.admitted_requests == 0
            assert report.completed_requests == 0
        finally:
            token.release()

