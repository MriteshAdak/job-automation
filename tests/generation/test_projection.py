"""Tests for projection intent dispatch, lost responses, and readback reconciliation (GEN-01-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import DocumentType, GenerationProcessing, PostingAvailability
from job_automation.contracts.errors import ClassifiedError
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
from job_automation.generation.projection import SalesforceRequestStateProjector
from job_automation.generation.records import ProjectionIntent, ProjectionStatus
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "proj_test.db"
    eng = StorageEngine(db_path=db_path, raw_dir=tmp_path / "raw", artifacts_dir=tmp_path / "art")
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


class TestStateProjection:
    def test_project_intent_acknowledges_on_gateway_success(self, engine: StorageEngine) -> None:
        gateway = FakeSalesforceGatewayV2()
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)

        sf_id = "a00111111111111AAA"
        # Seed record in fake gateway
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }

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
        # Directly insert into generation_requests
        engine.conn.execute(
            """
            INSERT INTO generation_requests (
                request_id, salesforce_request_id, canonical_job_id, document_type,
                target_language, template_id, context_strategy, allow_unavailable_job,
                state, created_at, claimed_at, request_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(req_id),
                sf_id,
                str(req.canonical_job_id),
                "cv",
                "de",
                "t1",
                "json",
                0,
                "running",
                now_utc.isoformat(),
                now_utc.isoformat(),
                req.model_dump_json(),
            ),
        )

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

        # Dispatch
        success, err = projector.project_intent(intent)
        assert success is True
        assert err is None

        # Verify DB intent is ACKNOWLEDGED
        saved_intent = engine.generation_work.get_projection_intent(req_id, 1)
        assert saved_intent is not None
        assert saved_intent.status == ProjectionStatus.ACKNOWLEDGED
        assert saved_intent.acknowledged_at is not None

        # Verify remote record updated
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Running"
        assert gateway.records["Generation_Request__c"][sf_id]["Operation_Marker__c"] == "op:test:1"

    def test_project_intent_uncertain_on_network_timeout(self, engine: StorageEngine) -> None:
        gateway = FakeSalesforceGatewayV2()
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)

        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }

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
        engine.conn.execute(
            """
            INSERT INTO generation_requests (
                request_id, salesforce_request_id, canonical_job_id, document_type,
                target_language, template_id, context_strategy, allow_unavailable_job,
                state, created_at, request_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(req_id),
                sf_id,
                str(req.canonical_job_id),
                "cv",
                "de",
                "t1",
                "json",
                0,
                "running",
                now_utc.isoformat(),
                req.model_dump_json(),
            ),
        )

        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker="op:timeout:1",
            desired_remote_state="Running",
            payload={"Status__c": "Running", "Operation_Marker__c": "op:timeout:1"},
            status=ProjectionStatus.PENDING,
            created_at=now_utc,
            updated_at=now_utc,
        )
        engine.generation_work.save_projection_intent(intent)

        # Simulate lost response timeout on update
        def update_hook(req):
            # Record was applied to Salesforce, but client gets uncertain timeout!
            gateway.records["Generation_Request__c"][sf_id]["Status__c"] = "Running"
            gateway.records["Generation_Request__c"][sf_id]["Operation_Marker__c"] = "op:timeout:1"
            return GatewayResult(
                failure=GatewayFailure(
                    error=ClassifiedError.transient_network("Connection reset by peer after commit"),
                    operation_kind=OperationKind.UPDATE_RECORD,
                    remote_outcome=RemoteOutcome.UNKNOWN,
                    recovery_action=RecoveryAction.RECONCILE,
                    attempts=[
                        AttemptSummary(
                            attempt_number=1,
                            purpose="update_record",
                            duration_ms=200.0,
                            uncertain_transmission=True,
                        )
                    ],
                )
            )

        gateway.update_record = update_hook

        success, err = projector.project_intent(intent)
        assert success is False

        # Intent must be marked UNCERTAIN
        saved_intent = engine.generation_work.get_projection_intent(req_id, 1)
        assert saved_intent is not None
        assert saved_intent.status == ProjectionStatus.UNCERTAIN
        assert saved_intent.uncertain_at is not None

        # Now test reconciliation: readback confirms matching marker!
        gateway.update_record = FakeSalesforceGatewayV2.update_record.__get__(gateway, FakeSalesforceGatewayV2)
        rec_success, rec_err = projector.reconcile_intent(saved_intent)
        assert rec_success is True
        assert rec_err is None

        reconciled_intent = engine.generation_work.get_projection_intent(req_id, 1)
        assert reconciled_intent is not None
        assert reconciled_intent.status == ProjectionStatus.ACKNOWLEDGED
        assert reconciled_intent.uncertain_at is None
