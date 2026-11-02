"""Tests for restart reconciliation, intent recovery, and stale remote running handling (GEN-01-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
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
from job_automation.generation.ports import GenerationRequestSource
from job_automation.generation.projection import SalesforceRequestStateProjector
from job_automation.generation.records import (
    FreezeManifest,
    GenerationRequestObservation,
    ProjectionIntent,
    ProjectionStatus,
    RemoteRequestState,
    StageCheckpoint,
    StageStatus,
)
from job_automation.generation.recovery import GenerationRecoveryManager
from job_automation.generation.request_mapping import (
    canonicalize_salesforce_id,
    derive_local_request_id,
)
from job_automation.generation.settings import GenerationSettings, GenerationStaleness
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


class FakeRecoverySource(GenerationRequestSource):
    def __init__(self, pending=None, running=None) -> None:
        self.pending = pending or []
        self.running = running or []

    def poll_requests(self, lane: str = "pending", limit: int = 10):
        if lane == "running":
            return self.running[:limit], [], None
        return self.pending[:limit], [], None


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    eng = StorageEngine(
        db_path=tmp_path / "recov.db",
        raw_dir=tmp_path / "raw",
        artifacts_dir=tmp_path / "art",
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


class TestGenerationRecovery:
    def test_reconcile_unacknowledged_pending_projection_intent(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        source = FakeRecoverySource()
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=source)

        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.RUNNING,
            created_at=now_utc,
            claimed_at=now_utc,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1",
                profile_version="prof-1",
                policy_version="pol-1",
                template_version="tmpl-1",
            ),
        )
        engine.generation_requests.create_request(req)

        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker="op:test:1",
            desired_remote_state="Running",
            payload={"Status__c": "Running", "Operation_Marker__c": "op:test:1"},
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        engine.generation_work.save_projection_intent(intent)

        # Recovery run
        actions = recovery.reconcile_all()
        assert any("Re-dispatched projection intent" in a for a in actions)

        updated_intent = engine.generation_work.get_projection_intent(req_id, 1)
        assert updated_intent is not None
        assert updated_intent.status == ProjectionStatus.ACKNOWLEDGED
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Running"

    def test_reconcile_uncertain_projection_intent_with_readback(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        # Remote record already received the marker during network glitch
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Running", "Operation_Marker__c": "op:glitch:1"}
        }
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        source = FakeRecoverySource()
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=source)

        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.RUNNING,
            created_at=now_utc,
            claimed_at=now_utc,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1",
                profile_version="prof-1",
                policy_version="pol-1",
                template_version="tmpl-1",
            ),
        )
        engine.generation_requests.create_request(req)

        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker="op:glitch:1",
            desired_remote_state="Running",
            payload={"Status__c": "Running", "Operation_Marker__c": "op:glitch:1"},
            status=ProjectionStatus.UNCERTAIN,
            created_at=now_utc,
            updated_at=now_utc,
            uncertain_at=now_utc,
        )
        engine.generation_work.save_projection_intent(intent)

        actions = recovery.reconcile_all()
        assert any("Reconciled projection intent" in a for a in actions)

        updated_intent = engine.generation_work.get_projection_intent(req_id, 1)
        assert updated_intent is not None
        assert updated_intent.status == ProjectionStatus.ACKNOWLEDGED

    def test_reconcile_local_unfinished_missing_freeze_marked_failed(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        source = FakeRecoverySource()
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=source)

        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        # Corrupt local request in RUNNING state but no freeze manifest exists in generation_freeze_associations!
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
                posting_revision="rev-1",
                profile_version="prof-1",
                policy_version="pol-1",
                template_version="tmpl-1",
            ),
        )
        engine.generation_requests.create_request(req)

        actions = recovery.reconcile_all()
        assert any("Marked corrupt request" in a for a in actions)

        updated_req = engine.generation_requests.get_request(req_id)
        assert updated_req is not None
        assert updated_req.state == GenerationProcessing.FAILED
        assert "Request claimed without frozen manifest" in updated_req.error.message

    def test_reconcile_stale_remote_running_with_local_freeze_resumes(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)

        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        # 40 minutes old running request (default threshold is 30m)
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=40)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            canonical_job_id=job_id,
            remote_state="Running",
            observed_at=datetime.now(timezone.utc),
            remote_updated_at=stale_time,
            raw_record={
                "Id": sf_id,
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Worker_Claimed_At__c": stale_time.isoformat(),
            },
        )
        source = FakeRecoverySource(running=[obs])
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=source)

        req_id = obs.local_request_id
        # Seed initial pending request
        pending_req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=canon_sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=stale_time,
        )
        engine.generation_requests.create_request(pending_req)

        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=canon_sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.RUNNING,
            created_at=stale_time,
            claimed_at=stale_time,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1",
                profile_version="prof-1",
                policy_version="pol-1",
                template_version="tmpl-1",
            ),
        )
        manifest = FreezeManifest(
            manifest_id=f"manifest:{req_id}",
            manifest_hash="sha256:" + "1" * 64,
            canonical_job_id=job_id,
            posting_revision_id="rev-1",
            posting_revision_hash="hash-1",
            profile_version="prof-1",
            policy_version="pol-1",
            template_id="t1",
            template_version="tmpl-1",
            context_strategy=ContextStrategy.JSON,
            target_language="de",
            options_digest="sha256:" + "2" * 64,
            frozen_at=stale_time,
        )
        chk = StageCheckpoint(
            request_id=req_id,
            stage_name="freeze",
            stage_operation_id=f"freeze:{req_id}",
            status=StageStatus.COMPLETED,
            started_at=stale_time,
            completed_at=stale_time,
        )
        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker=f"freeze:{req_id}",
            desired_remote_state="Running",
            payload={"Status__c": "Running"},
            status=ProjectionStatus.ACKNOWLEDGED,
            created_at=stale_time,
            updated_at=stale_time,
            acknowledged_at=stale_time,
        )
        engine.generation_work.commit_frozen_request(req, manifest, chk, intent)

        actions = recovery.reconcile_all()
        assert any("Resumed stale remote running request" in a for a in actions)

    def test_reconcile_stale_remote_running_orphan_projects_failure(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
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
            raw_record={
                "Id": sf_id,
                "Document_Type__c": "cv",
                "Worker_Claimed_At__c": stale_time.isoformat(),
            },
        )
        # Local database has NO record of this request and NO freeze manifest
        source = FakeRecoverySource(running=[obs])
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=source)

        actions = recovery.reconcile_all()
        assert any("Projected failure for stale orphan remote Running" in a for a in actions)

        # Assert remote record is now Failed, with error reason orphan_remote_running
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Failed"
        assert gateway.records["Generation_Request__c"][sf_id]["Error_Reason__c"] == "orphan_remote_running"

    def test_reconcile_fresh_remote_running_not_touched(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Running"}
        }
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)

        # Fresh running request (2 minutes ago)
        fresh_time = datetime.now(timezone.utc) - timedelta(minutes=2)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canonicalize_salesforce_id(sf_id),
            remote_state="Running",
            observed_at=datetime.now(timezone.utc),
            remote_updated_at=fresh_time,
            raw_record={
                "Id": sf_id,
                "Document_Type__c": "cv",
                "Worker_Claimed_At__c": fresh_time.isoformat(),
            },
        )
        source = FakeRecoverySource(running=[obs])
        recovery = GenerationRecoveryManager(engine=engine, projector=projector, source=source)

        actions = recovery.reconcile_all()
        assert len(actions) == 0
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Running"
