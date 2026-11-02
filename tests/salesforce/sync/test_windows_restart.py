"""Tests for storage restart and Windows process persistence (SYNC-01-S09)."""

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
    PublicationDecision,
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


class TestWindowsRestart:
    def test_windows_restart_with_in_flight_barriers_and_steps(self, tmp_path: Path) -> None:
        """Verify that steps in retry_wait, barriers, and selection heads survive a Windows process restart."""
        db_path = tmp_path / "sync_win_restart.db"
        config = load_sync_mapping_config(CONFIG_FILE)

        # Session 1: Enqueue job, simulate lost response, set barrier
        eng1 = StorageEngine(db_path=db_path)
        eng1.initialize_schema()

        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=comp_id,
            company_name="Windows Restart GmbH",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        eng1.canonical_jobs.save_canonical_job(canonical_job)

        # Pre-seed company mapping
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
            generation_token="gen-win-restart-token",
            job_title="DevOps Engineer",
            company_name="Windows Restart GmbH",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service1 = SyncService(eng1)
        plan_res = service1.commit_assessment_and_plan(sub, config)
        step_id = plan_res.plan.steps[0].step_id

        # Dispatch with lost response -> enters RETRY_WAIT and sets barrier
        gw1 = FakeSalesforceGatewayV2()
        gw1._simulate_lost_response_on_upsert = True
        dispatcher1 = SyncDispatcher(eng1)
        dispatcher1.drain_due_work(gw1, config)

        assert eng1.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is True
        step1 = eng1.sync_state.get_step(step_id)
        assert step1.state == SyncStepState.RETRY_WAIT
        assert step1.may_have_been_sent is True

        # Close session 1
        eng1.close()

        # Session 2: Reopen storage engine from cold start
        eng2 = StorageEngine(db_path=db_path)
        eng2.initialize_schema()

        # Barrier must still be active!
        assert eng2.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is True

        # Selection token must still be current!
        token = eng2.sync_state.get_selection_token(job_id)
        assert token == "gen-win-restart-token"

        # Step state preserved
        step2 = eng2.sync_state.get_step(step_id)
        assert step2.state == SyncStepState.RETRY_WAIT
        assert step2.may_have_been_sent is True
        assert step2.reconciliation_marker == step1.reconciliation_marker

        # Reconcile using gateway state (which committed the record)
        from job_automation.salesforce.sync_reconciliation import SyncReconciler
        reconciler2 = SyncReconciler(eng2)
        rec_res = reconciler2.reconcile_due_work(gw1, config)
        assert rec_res.steps_confirmed == 1

        # Barrier is now cleared, step is SUCCEEDED
        assert eng2.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is False
        step_final = eng2.sync_state.get_step(step_id)
        assert step_final.state == SyncStepState.SUCCEEDED
        assert step_final.acknowledged_at is not None

        eng2.close()

