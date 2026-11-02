"""Tests for ordered External ID delivery and step dispatch (SYNC-01-S06)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.enums import PostingAvailability
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_records import (
    EntityType,
    PublicationPurpose,
    SyncStepState,
    SyncSubmission,
)
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.salesforce.sync.test_publication import load_c11_fixture

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


class TestSyncDispatch:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_dispatch_test.db"
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
        company_name: str = "Dispatch Corp",
    ) -> None:
        now_dt = datetime.now(timezone.utc)
        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=company_id,
            company_name=company_name,
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

    def test_company_upserted_before_job_and_linked(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(engine, job_id, comp_id, "Dispatch Corp")

        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-dispatch-1",
            job_title="Backend Engineer",
            company_name="Dispatch Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        assert plan_res.is_published is True
        assert len(plan_res.plan.steps) == 2

        comp_step = plan_res.plan.steps[0]
        job_step = plan_res.plan.steps[1]

        assert comp_step.entity_type == EntityType.COMPANY
        assert job_step.entity_type == EntityType.JOB
        assert job_step.depends_on_step_id == comp_step.step_id

        dispatcher = SyncDispatcher(engine)
        drain = dispatcher.drain_due_work(gateway, config)

        assert drain.steps_succeeded == 2
        assert len(gateway.upsert_requests) == 2

        # 1. Company was sent first
        assert gateway.upsert_requests[0].object_name == config.company_object
        # 2. Job was sent second
        assert gateway.upsert_requests[1].object_name == config.job_object

        # Verify Job in Salesforce references Company's Salesforce ID
        job_rec = list(gateway.records[config.job_object].values())[0]
        comp_rec = list(gateway.records[config.company_object].values())[0]

        assert job_rec[config.job_company_lookup_field] == comp_rec["Id"]

        # Verify remote mappings committed locally
        c_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.company_object, comp_id)
        assert c_map is not None
        assert c_map.salesforce_id == comp_rec["Id"]

        j_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.job_object, job_id)
        assert j_map is not None
        assert j_map.salesforce_id == job_rec["Id"]

    def test_company_deduplication_reuses_remote_id(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        service = SyncService(engine)
        dispatcher = SyncDispatcher(engine)
        shared_company_id = uuid.uuid4()

        # Job 1
        asm_1 = load_c11_fixture("rules_only_eligible.json")
        job_1_id = asm_1.canonical_job_id
        self._seed_canonical_job(engine, job_1_id, shared_company_id, "Acme International")

        sub_1 = SyncSubmission(
            assessment=asm_1,
            canonical_job_id=job_1_id,
            posting_revision=asm_1.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-job-1",
            job_title="DevOps Lead",
            company_name="Acme International",
            canonical_company_id=shared_company_id,
            availability=PostingAvailability.ACTIVE,
        )
        service.commit_assessment_and_plan(sub_1, config)
        dispatcher.drain_due_work(gateway, config)

        assert len(gateway.records[config.company_object]) == 1
        comp_sf_id = list(gateway.records[config.company_object].keys())[0]

        # Job 2 with SAME company
        asm_2 = load_c11_fixture("llm_eligible.json")
        job_2_id = asm_2.canonical_job_id
        self._seed_canonical_job(engine, job_2_id, shared_company_id, "Acme International")

        sub_2 = SyncSubmission(
            assessment=asm_2,
            canonical_job_id=job_2_id,
            posting_revision=asm_2.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-job-2",
            job_title="ML Engineer",
            company_name="Acme International",
            canonical_company_id=shared_company_id,
            availability=PostingAvailability.ACTIVE,
        )
        plan_2_res = service.commit_assessment_and_plan(sub_2, config)
        assert plan_2_res.is_published is True

        # Plan 2 should NOT contain a Company step because Company is already acknowledged!
        assert len(plan_2_res.plan.steps) == 1
        assert plan_2_res.plan.steps[0].entity_type == EntityType.JOB
        assert plan_2_res.plan.steps[0].depends_on_step_id is None
        assert (
            plan_2_res.plan.steps[0].frozen_payload[config.job_company_lookup_field]
            == comp_sf_id
        )

        drain_2 = dispatcher.drain_due_work(gateway, config)
        assert drain_2.steps_succeeded == 1

        # Still only 1 company record in remote gateway
        assert len(gateway.records[config.company_object]) == 1
        assert len(gateway.records[config.job_object]) == 2

    def test_compare_and_set_claim_prevents_concurrent_dispatch(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(engine, job_id, comp_id, "Claim Corp")

        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-claim",
            job_title="Data Scientist",
            company_name="Claim Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        step_id = plan_res.plan.steps[0].step_id

        # Worker 1 claims step
        now_iso = datetime.now(timezone.utc).isoformat()
        claimed_w1 = engine.sync_state.claim_step(step_id, worker_id="worker-1", now_iso=now_iso)
        assert claimed_w1 is True

        # Worker 2 tries to claim same step -> must be rejected
        claimed_w2 = engine.sync_state.claim_step(step_id, worker_id="worker-2", now_iso=now_iso)
        assert claimed_w2 is False

        # Step state is now RUNNING
        step = engine.sync_state.get_step(step_id)
        assert step is not None
        assert step.state == SyncStepState.RUNNING
        assert step.attempt_count == 1
        assert step.may_have_been_sent is True
