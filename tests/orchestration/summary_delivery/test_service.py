"""Service lifecycle, retry checkpoints, lost acknowledgment, and outage recovery tests (T04, T06, T07, T08, T11)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.reporting import RunReport
from job_automation.orchestration.summary_delivery.adapter import (
    FakeSalesforceSummaryTargetAdapter,
)
from job_automation.orchestration.summary_delivery.records import (
    DeliveryState,
    NotificationState,
    RunCompletionReceipt,
)
from job_automation.orchestration.summary_delivery.service import SummaryDeliveryService
from job_automation.orchestration.summary_delivery.settings import SummaryDeliverySettings
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "database" / "job_automation.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()
    return engine


def _make_dummy_report(
    run_id: uuid.UUID,
    attempt: int = 1,
    status: RunStatus = RunStatus.SUCCESS,
) -> RunReport:
    now = datetime.now(timezone.utc)
    c15 = RunSummary(
        run_id=run_id,
        start_time=now,
        end_time=now,
        status=status,
        source_counts={"arbeitnow": 25},
        source_postings_count=25,
        canonical_jobs_new=4,
        canonical_jobs_updated=1,
        canonical_jobs_duplicate=20,
        eligible_count=2,
        review_count=1,
        rejected_count=1,
        sync_operations_succeeded=2,
        sync_operations_failed=0,
    )
    return RunReport(
        c15_summary=c15,
        attempt_sequence=attempt,
        assessment_mode="rules",
        sources_attempted=["arbeitnow"],
        sources_succeeded=["arbeitnow"],
        exit_code=0 if status == RunStatus.SUCCESS else (4 if status == RunStatus.PARTIAL else 1),
    )


class TestSummaryDeliveryService:
    def test_record_completion_and_deliver_success(self, storage: StorageEngine) -> None:
        """Full happy path: record terminal receipt -> deliver -> marked DELIVERED with 1 alert."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(
            enabled=True,
            salesforce_org_id=org_id,
            test_recipient="test_user@example.com",
        )
        fake_adapter = FakeSalesforceSummaryTargetAdapter(org_id=org_id, settings=settings)
        service = SummaryDeliveryService(engine=storage, settings=settings, target_adapter=fake_adapter)

        report = _make_dummy_report(run_id)

        # 1. Record completion
        receipt = service.record_run_completion(report)
        assert receipt.run_id == run_id
        assert receipt.revision == 1

        # Check outbox delivery created in state PENDING
        deliv = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv is not None
        assert deliv.state == DeliveryState.PENDING
        assert deliv.revision == 1

        # 2. Dispatch delivery
        deliv_rep = service.deliver_summary(run_id=run_id, test_recipient="test_user@example.com")
        assert deliv_rep.delivery_state == DeliveryState.DELIVERED
        assert deliv_rep.notification_state == NotificationState.CONFIRMED
        assert deliv_rep.remote_record_id is not None
        assert fake_adapter.remote_alert_count == 1

        # Check outbox state updated to DELIVERED
        deliv_after = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv_after is not None
        assert deliv_after.state == DeliveryState.DELIVERED
        assert deliv_after.remote_record_id == deliv_rep.remote_record_id
        assert deliv_after.acknowledged_at is not None

    def test_t06_lost_acknowledgment_recovery(self, storage: StorageEngine) -> None:
        """T06: Commit succeeds remotely but client receives timeout; reconciliation verifies remote ACK with 0 extra alerts."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(
            enabled=True,
            salesforce_org_id=org_id,
            test_recipient="test_user@example.com",
        )
        fake_adapter = FakeSalesforceSummaryTargetAdapter(org_id=org_id, settings=settings)
        service = SummaryDeliveryService(engine=storage, settings=settings, target_adapter=fake_adapter)

        report = _make_dummy_report(run_id)
        service.record_run_completion(report)

        # Simulate lost response: remote write commits, but client receives UNKNOWN / timeout
        fake_adapter.simulate_lost_response_on_upsert = True

        rep1 = service.deliver_summary(run_id=run_id)
        assert rep1.delivery_state == DeliveryState.RECONCILE_REQUIRED

        deliv = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv is not None
        assert deliv.state == DeliveryState.RECONCILE_REQUIRED
        assert deliv.dispatch_attempts == 1

        # Reconcile: reads back from target, finds matching payload hash -> transitions to DELIVERED
        rep2 = service.reconcile_delivery(run_id=run_id)
        assert rep2.delivery_state == DeliveryState.DELIVERED
        assert rep2.remote_record_id is not None
        assert rep2.notification_state == NotificationState.CONFIRMED

        # Verifies that Flow was NOT called again; alert count remains strictly 1!
        assert fake_adapter.remote_alert_count == 1

        deliv_final = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv_final is not None
        assert deliv_final.state == DeliveryState.DELIVERED

    def test_t07_authoritative_absence_replays_safely(self, storage: StorageEngine) -> None:
        """T07: When remote record is authoritatively absent on reconcile, transitions to PENDING to replay."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(enabled=True, salesforce_org_id=org_id)
        fake_adapter = FakeSalesforceSummaryTargetAdapter(org_id=org_id, settings=settings)
        service = SummaryDeliveryService(engine=storage, settings=settings, target_adapter=fake_adapter)

        report = _make_dummy_report(run_id)
        service.record_run_completion(report)

        # Manually set state to RECONCILE_REQUIRED without writing to fake adapter
        deliv = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv is not None
        storage.summary_deliveries.save_delivery(deliv.model_copy(update={"state": DeliveryState.RECONCILE_REQUIRED}))

        # Reconcile detects authoritative absence: transitions back to PENDING for safe dispatch
        rep = service.reconcile_delivery(run_id=run_id)
        assert rep.delivery_state == DeliveryState.PENDING

        deliv_after = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv_after is not None
        assert deliv_after.state == DeliveryState.PENDING

    def test_t07_hash_conflict_blocks_delivery(self, storage: StorageEngine) -> None:
        """T07: When remote record has differing payload hash, transitions to BLOCKED for operator repair."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(enabled=True, salesforce_org_id=org_id)
        fake_adapter = FakeSalesforceSummaryTargetAdapter(org_id=org_id, settings=settings)
        service = SummaryDeliveryService(engine=storage, settings=settings, target_adapter=fake_adapter)

        report = _make_dummy_report(run_id)
        service.record_run_completion(report)

        # Inject remote record with conflicting hash
        fake_adapter.records[str(run_id)] = {
            "Id": "a05ConflictRecord",
            "Run_Id__c": str(run_id),
            "Revision__c": 1,
            "Payload_Hash__c": "completely_different_hash_from_another_machine",
            "Notification_Status__c": "confirmed",
        }

        # Set delivery to RECONCILE_REQUIRED
        deliv = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv is not None
        storage.summary_deliveries.save_delivery(deliv.model_copy(update={"state": DeliveryState.RECONCILE_REQUIRED}))

        rep = service.reconcile_delivery(run_id=run_id)
        assert rep.delivery_state == DeliveryState.BLOCKED
        assert "PAYLOAD_HASH_MISMATCH" in (rep.last_error or "")

        deliv_after = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv_after is not None
        assert deliv_after.state == DeliveryState.BLOCKED

    def test_t08_recovery_after_notification_service_outage(self, storage: StorageEngine) -> None:
        """T08: When notification service fails initially, recovery confirms notification without duplicate alert."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(
            enabled=True,
            salesforce_org_id=org_id,
            test_recipient="test_user@example.com",
        )
        fake_adapter = FakeSalesforceSummaryTargetAdapter(org_id=org_id, settings=settings)
        service = SummaryDeliveryService(engine=storage, settings=settings, target_adapter=fake_adapter)

        report = _make_dummy_report(run_id)
        service.record_run_completion(report)

        # Outage during initial send
        fake_adapter.simulate_notification_service_outage = True
        rep1 = service.deliver_summary(run_id=run_id)
        assert rep1.delivery_state == DeliveryState.DELIVERED
        assert rep1.notification_state == NotificationState.FAILED
        assert fake_adapter.remote_alert_count == 0

        # Outage resolves in remote system (e.g. queue drains)
        fake_adapter.simulate_notification_service_outage = False
        fake_adapter.records[str(run_id)]["Notification_Status__c"] = "confirmed"
        fake_adapter.records[str(run_id)]["Notification_Receipt_Id__c"] = "outage_recovery_receipt_123"
        fake_adapter.remote_alert_count = 1

        # Subsequent reconciliation observes confirmed status
        rep2 = service.reconcile_delivery(run_id=run_id)
        assert rep2.delivery_state == DeliveryState.DELIVERED
        assert rep2.notification_state == NotificationState.CONFIRMED

        deliv_final = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv_final is not None
        assert deliv_final.notification_state == NotificationState.CONFIRMED
        assert fake_adapter.remote_alert_count == 1

    def test_t08_transient_outage_backoff_and_exhaustion(self, storage: StorageEngine) -> None:
        """T08: Server 503 error transitions to RETRY_WAIT, increments attempts, and exhausts at limit."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(
            enabled=True,
            salesforce_org_id=org_id,
            max_dispatch_attempts=2,
            initial_backoff_seconds=1.0,
        )
        fake_adapter = FakeSalesforceSummaryTargetAdapter(org_id=org_id, settings=settings)
        fake_adapter.simulate_server_error = True

        service = SummaryDeliveryService(engine=storage, settings=settings, target_adapter=fake_adapter)
        report = _make_dummy_report(run_id)
        service.record_run_completion(report)

        # Attempt 1: 503 error -> RETRY_WAIT
        rep1 = service.deliver_summary(run_id=run_id)
        assert rep1.delivery_state == DeliveryState.RETRY_WAIT
        assert rep1.dispatch_attempts == 1
        assert rep1.next_due_at is not None

        # Attempt 2 (force): 503 error -> reaches max 2 attempts -> EXHAUSTED
        rep2 = service.deliver_summary(run_id=run_id, force=True)
        assert rep2.delivery_state == DeliveryState.EXHAUSTED
        assert rep2.dispatch_attempts == 2

    def test_t11_manual_repair_reset_retry(self, storage: StorageEngine) -> None:
        """T11: Manual repair resets budget, extends deadline, and transitions to RECONCILE_REQUIRED."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(enabled=True, salesforce_org_id=org_id, max_dispatch_attempts=2)
        service = SummaryDeliveryService(engine=storage, settings=settings)

        report = _make_dummy_report(run_id)
        service.record_run_completion(report)

        # Mark exhausted
        deliv = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv is not None
        storage.summary_deliveries.save_delivery(
            deliv.model_copy(update={"state": DeliveryState.EXHAUSTED, "dispatch_attempts": 2})
        )

        # Operator triggers manual retry reset
        updated = service.reset_retry(run_id=run_id, additional_attempts=3)
        assert updated.state == DeliveryState.RECONCILE_REQUIRED
        assert updated.dispatch_attempts == 0
        assert updated.retry_deadline > datetime.now(timezone.utc)

    def test_bounded_repair_scanner_recovers_missing_delivery(self, storage: StorageEngine) -> None:
        """Scanner synthesizes outbox delivery for orphaned receipt without stage re-execution."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        settings = SummaryDeliverySettings(enabled=True, salesforce_org_id=org_id)
        service = SummaryDeliveryService(engine=storage, settings=settings)

        # Save receipt directly (simulating crash before delivery outbox commit)
        report = _make_dummy_report(run_id)
        now = datetime.now(timezone.utc)
        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=report.c15_summary,
        )
        storage.summary_deliveries.save_receipt(receipt)

        # Delivery does not exist yet
        assert storage.summary_deliveries.get_delivery(org_id, run_id) is None

        # Run scanner repair
        repaired_cnt = service.repair_unregistered_completions(org_id=org_id)
        assert repaired_cnt == 1

        deliv = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert deliv is not None
        assert deliv.state == DeliveryState.PENDING
        assert deliv.run_id == run_id
