"""Tests for lost-response reconciliation (SYNC-01-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_reconciliation import SyncReconciler
from job_automation.salesforce.sync_records import (
    EntityType,
    SyncStepState,
    SyncSubmission,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.salesforce.sync.test_publication import load_c11_fixture

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


class TestSyncReconciliation:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_reconcile_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    @pytest.fixture
    def gateway(self) -> FakeSalesforceGatewayV2:
        return FakeSalesforceGatewayV2()

    def _seed_canonical_job(
        self,
        engine: StorageEngine,
        job_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> None:
        now_dt = datetime.now(timezone.utc)
        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=company_id,
            company_name="Reconcile Corp",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

    def test_lost_response_reconciled_via_external_id_and_marker(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        """Simulate write committed remotely, gateway returned timeout.
        Reconciler reads back by External ID, finds matching Sync_Operation_Marker__c,
        marks step succeeded, commits mapping, and clears barrier.
        """
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(engine, job_id, comp_id)

        # 1. Pre-register acknowledged Company mapping so we only test Job write
        c_map = engine.sync_state.allocate_sequence(config.expected_org_id, config.company_object, comp_id)
        now_dt = datetime.now(timezone.utc)
        from job_automation.salesforce.sync_records import RemoteEntityMapping
        engine.sync_state.save_remote_mapping(
            RemoteEntityMapping(
                org_id=config.expected_org_id,
                object_name=config.company_object,
                entity_id=comp_id,
                external_id=f"comp-{comp_id}",
                salesforce_id="a00Company0000001",
                confirmed_sequence=1,
                acknowledged_at=now_dt,
            )
        )

        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-reconcile-1",
            job_title="Security Engineer",
            company_name="Reconcile Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        job_step = plan_res.plan.steps[0]

        # 2. Simulate lost response on upsert:
        # Gateway writes the record, but returns UNKNOWN failure to the client!
        gateway._simulate_lost_response_on_upsert = True

        dispatcher = SyncDispatcher(engine)
        drain = dispatcher.drain_due_work(gateway, config)

        assert drain.steps_succeeded == 0
        assert drain.steps_failed == 1

        # Verify step entered retry_wait / uncertain state and barrier was placed
        step_after = engine.sync_state.get_step(job_step.step_id)
        assert step_after is not None
        assert step_after.state == SyncStepState.RETRY_WAIT
        assert step_after.may_have_been_sent is True
        assert engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is True

        # 3. Run Reconciler:
        reconciler = SyncReconciler(engine)
        rec_res = reconciler.reconcile_due_work(gateway, config)

        assert rec_res.steps_checked == 1
        assert rec_res.steps_confirmed == 1
        assert rec_res.barriers_retained == 0

        # Step is now SUCCEEDED, barrier cleared, mapping saved!
        step_confirmed = engine.sync_state.get_step(job_step.step_id)
        assert step_confirmed is not None
        assert step_confirmed.state == SyncStepState.SUCCEEDED
        assert step_confirmed.remote_record_id is not None
        assert step_confirmed.acknowledged_at is not None

        assert engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is False

        j_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.job_object, job_id)
        assert j_map is not None
        assert j_map.salesforce_id == step_confirmed.remote_record_id

    def test_reconciliation_detects_newer_remote_version(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        """When remote record exists with a higher sequence number than our uncertain step,
        mark older step superseded and clear barrier.
        """
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(engine, job_id, comp_id)

        # Create an uncertain step locally with sequence_number = 1
        from job_automation.salesforce.sync_records import SyncPlan, SyncWriteStep, PublicationDecision
        from job_automation.salesforce.sync_serialization import calculate_step_fingerprint
        plan_id = uuid.uuid4()
        step_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        step = SyncWriteStep(
            step_id=step_id,
            plan_id=plan_id,
            entity_type=EntityType.JOB,
            entity_id=job_id,
            sequence_number=1,
            target_object=config.job_object,
            external_id_field=config.job_external_id_field,
            external_id_value=f"job-{job_id}",
            frozen_payload={"Name": "Job V1"},
            step_fingerprint="fp1",
            reconciliation_marker="marker-v1",
            state=SyncStepState.RETRY_WAIT,
            may_have_been_sent=True,
            attempt_count=1,
        )
        plan = SyncPlan(
            plan_id=plan_id,
            canonical_job_id=job_id,
            assessment_id=asm.assessment_id,
            mapping_version="1.0",
            mapping_hash="hash",
            plan_fingerprint="fp",
            selection_token="token",
            publication_decision=PublicationDecision.PUBLISH_INITIAL,
            created_at=now_dt,
            steps=[step],
        )
        engine.sync_state.commit_plan_and_steps(plan=plan, assessment=asm)
        engine.sync_state.set_barrier(config.expected_org_id, config.job_object, job_id, "Uncertain")

        # Remote record has sequence 2 (newer!)
        remote_rec_id = "a00Job000000002AAA"
        gateway.records.setdefault(config.job_object, {})[remote_rec_id] = {
            "Id": remote_rec_id,
            config.job_external_id_field: f"job-{job_id}",
            config.sync_version_field: 2,
            config.sync_marker_field: "marker-v2-from-newer-client",
        }
        gateway.external_ids.setdefault(config.job_object, {})[f"job-{job_id}"] = remote_rec_id

        # Reconcile
        reconciler = SyncReconciler(engine)
        rec_res = reconciler.reconcile_due_work(gateway, config)

        assert rec_res.steps_superseded == 1
        assert engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is False

        step_final = engine.sync_state.get_step(step_id)
        assert step_final is not None
        assert step_final.state == SyncStepState.FAILED
        assert "Superseded" in (step_final.error.message if step_final.error else "")
