"""Tests for bounded retries, exponential backoff, and failure classification (SYNC-01-S08)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.salesforce import (
    GatewayFailure,
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
)
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_records import (
    RemoteEntityMapping,
    SyncStepState,
    SyncSubmission,
)
from job_automation.salesforce.sync_retry import (
    DEFAULT_MAX_ATTEMPTS,
    calculate_sync_backoff,
    compute_next_attempt_at,
    is_safely_retryable,
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


class TestSyncRetry:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_retry_test.db"
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
            company_name="Retry Corp",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

    def test_transient_failure_enters_retry_wait_with_backoff(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        self._seed_canonical_job(engine, job_id, comp_id)

        # Pre-seed company mapping
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
            generation_token="gen-retry-1",
            job_title="Reliability Engineer",
            company_name="Retry Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        job_step = plan_res.plan.steps[0]

        # Program transient 503 error (safe retryable, known not committed)
        gateway._next_upsert_failure = GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                "Salesforce 503 Service Unavailable",
            ),
            http_status=503,
            operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.RETRY_LATER,
        )

        dispatcher = SyncDispatcher(engine)
        drain = dispatcher.drain_due_work(gateway, config)

        assert drain.steps_succeeded == 0
        assert drain.steps_failed == 1

        step_after = engine.sync_state.get_step(job_step.step_id)
        assert step_after is not None
        assert step_after.state == SyncStepState.RETRY_WAIT
        assert step_after.attempt_count == 1
        assert step_after.next_attempt_at is not None
        assert step_after.next_attempt_at > now_dt

        # Immediate re-drain skips the step because next_attempt_at has not elapsed
        drain_2 = dispatcher.drain_due_work(gateway, config)
        assert drain_2.operations_claimed == 0

    def test_honors_retry_not_before(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
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
            generation_token="gen-retry-2",
            job_title="Reliability Engineer",
            company_name="Retry Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        job_step = plan_res.plan.steps[0]

        # Program 429 Rate Limit with Retry-After 60s
        retry_not_before = now_dt + timedelta(seconds=60)
        gateway._next_upsert_failure = GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.RATE_LIMIT,
                "API Request Limit Exceeded",
            ),
            http_status=429,
            operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.RETRY_LATER,
            retry_not_before=retry_not_before,
        )

        dispatcher = SyncDispatcher(engine)
        dispatcher.drain_due_work(gateway, config)

        step_after = engine.sync_state.get_step(job_step.step_id)
        assert step_after is not None
        assert step_after.state == SyncStepState.RETRY_WAIT
        assert step_after.next_attempt_at is not None
        assert step_after.next_attempt_at >= retry_not_before

    def test_max_attempts_exceeded_becomes_terminal_failed(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
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
            generation_token="gen-retry-3",
            job_title="Reliability Engineer",
            company_name="Retry Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        job_step = plan_res.plan.steps[0]

        dispatcher = SyncDispatcher(engine)

        # Attempt 1 -> fails to retry_wait
        gateway._next_upsert_failure = GatewayFailure(
            error=ClassifiedError.from_category(ErrorCategory.TRANSIENT_NETWORK, "Network dropped"),
            http_status=None,
            operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.RETRY_LATER,
        )
        dispatcher.drain_due_work(gateway, config)
        step = engine.sync_state.get_step(job_step.step_id)
        assert step.state == SyncStepState.RETRY_WAIT
        assert step.attempt_count == 1

        # Force due time to past for Attempt 2
        engine.conn.execute(
            "UPDATE sync_write_steps SET next_attempt_at = ? WHERE step_id = ?",
            (datetime.now(timezone.utc).isoformat(), str(job_step.step_id)),
        )

        gateway._next_upsert_failure = GatewayFailure(
            error=ClassifiedError.from_category(ErrorCategory.TRANSIENT_NETWORK, "Network dropped again"),
            http_status=None,
            operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.RETRY_LATER,
        )
        dispatcher.drain_due_work(gateway, config)
        step = engine.sync_state.get_step(job_step.step_id)
        assert step.state == SyncStepState.RETRY_WAIT
        assert step.attempt_count == 2

        # Force due time to past for Attempt 3 (final attempt)
        engine.conn.execute(
            "UPDATE sync_write_steps SET next_attempt_at = ? WHERE step_id = ?",
            (datetime.now(timezone.utc).isoformat(), str(job_step.step_id)),
        )

        gateway._next_upsert_failure = GatewayFailure(
            error=ClassifiedError.from_category(ErrorCategory.TRANSIENT_NETWORK, "Network dropped final"),
            http_status=None,
            operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.RETRY_LATER,
        )
        dispatcher.drain_due_work(gateway, config)

        # Attempt 3: DEFAULT_MAX_ATTEMPTS reached -> terminal FAILED!
        step_final = engine.sync_state.get_step(job_step.step_id)
        assert step_final.state == SyncStepState.FAILED
        assert step_final.attempt_count == 3
        assert step_final.next_attempt_at is None

    def test_permanent_permission_error_fails_immediately(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
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
            generation_token="gen-retry-perm",
            job_title="Reliability Engineer",
            company_name="Retry Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        job_step = plan_res.plan.steps[0]

        # Program 403 Forbidden / PERMISSION error
        gateway._next_upsert_failure = GatewayFailure(
            error=ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                "Insufficient access rights on object Job__c",
            ),
            http_status=403,
            operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
            remote_outcome=RemoteOutcome.NOT_SENT,
            recovery_action=RecoveryAction.FIX_CONFIGURATION,
        )

        dispatcher = SyncDispatcher(engine)
        dispatcher.drain_due_work(gateway, config)

        step_after = engine.sync_state.get_step(job_step.step_id)
        assert step_after is not None
        # Fails immediately on attempt 1 without retry_wait!
        assert step_after.state == SyncStepState.FAILED
        assert step_after.attempt_count == 1
        assert step_after.next_attempt_at is None
