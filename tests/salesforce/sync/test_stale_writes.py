"""Tests for stale-write prevention and per-entity lane barriers (SYNC-01-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_records import (
    EntityType,
    PublicationPurpose,
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


class TestStaleWrites:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_stale_test.db"
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
            company_name="Barrier Corp",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

    def test_active_barrier_blocks_subsequent_dispatch(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        """When an uncertainty barrier exists on an entity lane,
        the dispatcher skips all due steps for that entity until the barrier is cleared.
        """
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(engine, job_id, comp_id)

        # Pre-register company
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
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-barrier-1",
            job_title="DevSecOps Lead",
            company_name="Barrier Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        job_step = plan_res.plan.steps[0]

        # Artificially set barrier on the job lane
        engine.sync_state.set_barrier(
            config.expected_org_id,
            config.job_object,
            job_id,
            reason="Uncertain in-flight transmission",
        )
        assert engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is True

        # Dispatch should skip this step because of the barrier
        dispatcher = SyncDispatcher(engine)
        drain = dispatcher.drain_due_work(gateway, config)

        assert drain.steps_succeeded == 0
        assert drain.operations_claimed == 0
        assert gateway.physical_upsert_count == 0

        # Step remains PENDING
        step_status = engine.sync_state.get_step(job_step.step_id)
        assert step_status is not None
        assert step_status.state == SyncStepState.PENDING

        # Clear barrier
        engine.sync_state.clear_barrier(config.expected_org_id, config.job_object, job_id)
        assert engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is False

        # Now dispatch succeeds!
        drain_2 = dispatcher.drain_due_work(gateway, config)
        assert drain_2.steps_succeeded == 1
        assert gateway.physical_upsert_count == 1

    def test_replay_cannot_regress_confirmed_sequence(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
    ) -> None:
        """Remote mapping confirmed sequence is strictly monotonic.
        An older sequence (e.g. 1) cannot regress a newer sequence (e.g. 2).
        """
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        # 1. Save mapping at sequence 2
        engine.sync_state.save_remote_mapping(
            RemoteEntityMapping(
                org_id=config.expected_org_id,
                object_name=config.job_object,
                entity_id=job_id,
                external_id=f"job-{job_id}",
                salesforce_id="a00Job000000002AAA",
                confirmed_sequence=2,
                acknowledged_at=now_dt,
            )
        )

        mapping = engine.sync_state.get_remote_mapping(config.expected_org_id, config.job_object, job_id)
        assert mapping is not None
        assert mapping.confirmed_sequence == 2

        # 2. Try to save older mapping at sequence 1
        engine.sync_state.save_remote_mapping(
            RemoteEntityMapping(
                org_id=config.expected_org_id,
                object_name=config.job_object,
                entity_id=job_id,
                external_id=f"job-{job_id}",
                salesforce_id="a00Job000000001AAA",
                confirmed_sequence=1,
                acknowledged_at=now_dt,
            )
        )

        # Sequence must NOT regress!
        mapping_after = engine.sync_state.get_remote_mapping(config.expected_org_id, config.job_object, job_id)
        assert mapping_after is not None
        assert mapping_after.confirmed_sequence == 2

