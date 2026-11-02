"""Tests for operational recovery, budget enforcement, and process restart (SYNC-01-S08)."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.budget import CallBudget
from job_automation.salesforce.ports import DefaultClock
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_records import (
    RemoteEntityMapping,
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


class TestSyncRecovery:
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
            company_name="Recovery Corp",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

    def test_bounded_operations_limit_honored(
        self,
        tmp_path: Path,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        """Dispatcher respects max_operations bound per drain pass."""
        db_path = tmp_path / "sync_bounded.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        service = SyncService(engine)
        dispatcher = SyncDispatcher(engine)

        # Enqueue 2 independent jobs
        now_dt = datetime.now(timezone.utc)
        for i in range(1, 3):
            asm = load_c11_fixture("rules_only_eligible.json")
            jid = uuid.uuid4()
            cid = uuid.uuid4()
            # Modify asm canonical job id
            asm_copy = asm.model_copy(update={"canonical_job_id": jid, "assessment_id": uuid.uuid4()})
            self._seed_canonical_job(engine, jid, cid)
            # Pre-seed company mapping to isolate job write
            engine.sync_state.save_remote_mapping(
                RemoteEntityMapping(
                    org_id=config.expected_org_id,
                    object_name=config.company_object,
                    entity_id=cid,
                    external_id=f"comp-{cid}",
                    salesforce_id=f"a00Company000000{i}",
                    confirmed_sequence=1,
                    acknowledged_at=now_dt,
                )
            )
            sub = SyncSubmission(
                assessment=asm_copy,
                canonical_job_id=jid,
                posting_revision=asm.posting_revision,
                evaluated_at=now_dt,
                generation_token=f"gen-bound-{i}",
                job_title=f"Engineer {i}",
                company_name="Recovery Corp",
                canonical_company_id=cid,
                availability=PostingAvailability.ACTIVE,
            )
            service.commit_assessment_and_plan(sub, config)

        # Drain with max_operations = 1
        drain_1 = dispatcher.drain_due_work(gateway, config, max_operations=1)
        assert drain_1.operations_claimed == 1
        assert drain_1.steps_succeeded == 1
        assert drain_1.remaining_due == 1

        # Second drain pass picks up the second operation
        drain_2 = dispatcher.drain_due_work(gateway, config, max_operations=1)
        assert drain_2.operations_claimed == 1
        assert drain_2.steps_succeeded == 1
        assert drain_2.remaining_due == 0

        engine.close()

    def test_call_budget_exhaustion_stops_drain(
        self,
        tmp_path: Path,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        """When CallBudget is exhausted, dispatcher stops without performing further work."""
        db_path = tmp_path / "sync_budget.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(engine, job_id, comp_id)

        now_dt = datetime.now(timezone.utc)
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
            evaluated_at=now_dt,
            generation_token="gen-budget-1",
            job_title="Software Engineer",
            company_name="Recovery Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service = SyncService(engine)
        service.commit_assessment_and_plan(sub, config)

        # Create exhausted budget (max_total_sends=1, already sent 1)
        clock = DefaultClock()
        budget = CallBudget(clock=clock, total_timeout_seconds=60.0, max_total_sends=1)
        budget.record_resource_send()
        assert budget.is_exhausted() is True

        dispatcher = SyncDispatcher(engine)
        drain = dispatcher.drain_due_work(gateway, config, budget=budget)

        assert drain.operations_claimed == 0
        assert drain.steps_succeeded == 0
        assert gateway.physical_upsert_count == 0

        engine.close()

    def test_storage_restart_persists_outbox_state(
        self,
        tmp_path: Path,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        """Closing and reopening StorageEngine retains all pending plans and steps."""
        db_path = tmp_path / "sync_restart.db"

        # 1. Open engine, seed job, commit plan
        eng1 = StorageEngine(db_path=db_path)
        eng1.initialize_schema()

        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(eng1, job_id, comp_id)

        now_dt = datetime.now(timezone.utc)
        eng1.sync_state.save_remote_mapping(
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
            evaluated_at=now_dt,
            generation_token="gen-restart-1",
            job_title="Restart Engineer",
            company_name="Recovery Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service1 = SyncService(eng1)
        plan_res = service1.commit_assessment_and_plan(sub, config)
        step_id = plan_res.plan.steps[0].step_id

        # Close engine 1 (simulating process restart)
        eng1.close()

        # 2. Open new engine instance on the same file
        eng2 = StorageEngine(db_path=db_path)
        eng2.initialize_schema()

        step_recovered = eng2.sync_state.get_step(step_id)
        assert step_recovered is not None
        assert step_recovered.state == SyncStepState.PENDING
        assert step_recovered.external_id_value == str(job_id)

        # Dispatch with engine 2
        dispatcher2 = SyncDispatcher(eng2)
        drain = dispatcher2.drain_due_work(gateway, config)

        assert drain.steps_succeeded == 1
        assert gateway.physical_upsert_count == 1

        step_final = eng2.sync_state.get_step(step_id)
        assert step_final.state == SyncStepState.SUCCEEDED
        assert step_final.acknowledged_at is not None

        eng2.close()
