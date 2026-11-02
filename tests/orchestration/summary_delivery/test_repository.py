"""Storage and repository persistence tests for AUTO-03 (T05, T10, T14)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.summary_delivery.records import (
    DeliveryAttemptRecord,
    DeliveryState,
    NotificationState,
    RunCompletionReceipt,
    SummaryDelivery,
)
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "database" / "job_automation.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()
    return engine


def _make_dummy_receipt(run_id: uuid.UUID, revision: int = 1) -> RunCompletionReceipt:
    now = datetime.now(timezone.utc)
    c15 = RunSummary(
        run_id=run_id,
        start_time=now,
        end_time=now,
        status=RunStatus.SUCCESS,
        source_counts={"arbeitnow": 10},
        source_postings_count=10,
        canonical_jobs_new=2,
    )
    return RunCompletionReceipt(
        run_id=run_id,
        attempt_sequence=revision,
        revision=revision,
        start_time=now,
        completed_at=now,
        status="success",
        c15_summary=c15,
        sources_attempted=["arbeitnow"],
        sources_succeeded=["arbeitnow"],
    )


def _make_dummy_delivery(
    org_id: str,
    run_id: uuid.UUID,
    state: DeliveryState = DeliveryState.PENDING,
    next_due_at: datetime | None = None,
) -> SummaryDelivery:
    now = datetime.now(timezone.utc)
    return SummaryDelivery(
        run_id=run_id,
        org_id=org_id,
        completion_key=f"{org_id}:{run_id}",
        revision=1,
        state=state,
        payload_json=json.dumps({"run_id": str(run_id)}),
        payload_hash="hash_123",
        first_completion_hash="hash_123",
        retry_window_start=now,
        retry_deadline=now + timedelta(hours=48),
        next_due_at=next_due_at or now,
    )


class TestSummaryDeliveryRepository:
    def test_save_and_get_receipt(self, storage: StorageEngine) -> None:
        run_id = uuid.uuid4()
        receipt = _make_dummy_receipt(run_id, revision=1)
        storage.summary_deliveries.save_receipt(receipt)

        loaded = storage.summary_deliveries.get_receipt(run_id, revision=1)
        assert loaded is not None
        assert loaded.run_id == run_id
        assert loaded.revision == 1
        assert loaded.c15_summary.source_postings_count == 10

    def test_list_receipts_multiple_revisions(self, storage: StorageEngine) -> None:
        run_id = uuid.uuid4()
        r1 = _make_dummy_receipt(run_id, revision=1)
        r2 = _make_dummy_receipt(run_id, revision=2)
        storage.summary_deliveries.save_receipt(r1)
        storage.summary_deliveries.save_receipt(r2)

        recs = storage.summary_deliveries.list_receipts(run_id)
        assert len(recs) == 2
        assert [r.revision for r in recs] == [1, 2]

        latest = storage.summary_deliveries.get_receipt(run_id)
        assert latest is not None
        assert latest.revision == 2

    def test_save_and_get_delivery(self, storage: StorageEngine) -> None:
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        delivery = _make_dummy_delivery(org_id, run_id)
        storage.summary_deliveries.save_delivery(delivery)

        loaded = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert loaded is not None
        assert loaded.run_id == run_id
        assert loaded.state == DeliveryState.PENDING
        assert loaded.completion_key == f"{org_id}:{run_id}"

        # Fetch by run ID convenience
        loaded_by_run = storage.summary_deliveries.get_delivery_by_run_id(run_id)
        assert loaded_by_run is not None
        assert loaded_by_run.org_id == org_id

    def test_unique_lane_per_org_and_run(self, storage: StorageEngine) -> None:
        """Upserting delivery for same org and run updates rather than creates duplicate row."""
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        d1 = _make_dummy_delivery(org_id, run_id, state=DeliveryState.PENDING)
        storage.summary_deliveries.save_delivery(d1)

        d2 = d1.model_copy(update={"state": DeliveryState.DELIVERED, "remote_record_id": "a05Rec1"})
        storage.summary_deliveries.save_delivery(d2)

        all_items = storage.summary_deliveries.list_deliveries()
        assert len(all_items) == 1
        assert all_items[0].state == DeliveryState.DELIVERED
        assert all_items[0].remote_record_id == "a05Rec1"

    def test_t10_claim_due_deliveries(self, storage: StorageEngine) -> None:
        """T10: Atomic claiming transitions pending/retry_wait to in_flight with claim token."""
        org_id = "00D000000000001"
        now = datetime.now(timezone.utc)
        run1 = uuid.uuid4()
        run2 = uuid.uuid4()
        run3_future = uuid.uuid4()

        d1 = _make_dummy_delivery(org_id, run1, state=DeliveryState.PENDING, next_due_at=now - timedelta(seconds=10))
        d2 = _make_dummy_delivery(org_id, run2, state=DeliveryState.RETRY_WAIT, next_due_at=now)
        d3 = _make_dummy_delivery(org_id, run3_future, state=DeliveryState.RETRY_WAIT, next_due_at=now + timedelta(hours=1))

        storage.summary_deliveries.save_delivery(d1)
        storage.summary_deliveries.save_delivery(d2)
        storage.summary_deliveries.save_delivery(d3)

        token = "worker_token_abc"
        claimed = storage.summary_deliveries.claim_due_deliveries(org_id, claim_token=token, limit=10, as_of=now)

        assert len(claimed) == 2
        claimed_ids = {c.run_id for c in claimed}
        assert run1 in claimed_ids
        assert run2 in claimed_ids
        assert run3_future not in claimed_ids

        for c in claimed:
            assert c.state == DeliveryState.IN_FLIGHT
            assert c.claim_token == token

    def test_t10_stale_in_flight_recovery(self, storage: StorageEngine) -> None:
        """T10: Dead worker claims recover to reconcile_required."""
        org_id = "00D000000000001"
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        d = _make_dummy_delivery(org_id, run_id, state=DeliveryState.PENDING)
        storage.summary_deliveries.save_delivery(d)

        # Claim
        storage.summary_deliveries.claim_due_deliveries(org_id, "token_1", as_of=now)

        # Stale threshold: 5 minutes ago. Record was claimed now, so not stale yet:
        recovered = storage.summary_deliveries.claim_stale_in_flight(org_id, stale_before=now - timedelta(minutes=5))
        assert recovered == 0

        # With stale_before in future, it recovers:
        recovered = storage.summary_deliveries.claim_stale_in_flight(org_id, stale_before=now + timedelta(seconds=1))
        assert recovered == 1

        updated = storage.summary_deliveries.get_delivery(org_id, run_id)
        assert updated is not None
        assert updated.state == DeliveryState.RECONCILE_REQUIRED
        assert updated.claim_token is None

    def test_attempts_audit_logging(self, storage: StorageEngine) -> None:
        deliv_id = uuid.uuid4()
        run_id = uuid.uuid4()
        org_id = "00D000000000001"
        delivery = _make_dummy_delivery(org_id, run_id)
        delivery = delivery.model_copy(update={"delivery_id": deliv_id})
        storage.summary_deliveries.save_delivery(delivery)

        att1 = DeliveryAttemptRecord(
            delivery_id=deliv_id,
            run_id=run_id,
            attempt_sequence=1,
            operation_kind="upsert",
            status="failed",
            http_status=503,
            remote_outcome="not_sent",
            recovery_action="retry_later",
            safe_error_code="UNAVAILABLE",
        )
        att2 = DeliveryAttemptRecord(
            delivery_id=deliv_id,
            run_id=run_id,
            attempt_sequence=2,
            operation_kind="upsert",
            status="succeeded",
            http_status=200,
            remote_outcome="acknowledged",
        )
        storage.summary_deliveries.save_attempt(att1)
        storage.summary_deliveries.save_attempt(att2)

        history = storage.summary_deliveries.list_attempts(deliv_id)
        assert len(history) == 2
        assert history[0].attempt_sequence == 1
        assert history[0].status == "failed"
        assert history[1].attempt_sequence == 2
        assert history[1].status == "succeeded"

    def test_t05_unregistered_terminal_receipts_scanner(self, storage: StorageEngine) -> None:
        """T05: Scanner discovers receipts committed without outbox delivery entity."""
        run1 = uuid.uuid4()
        run2 = uuid.uuid4()
        org_id = "00D000000000001"

        r1 = _make_dummy_receipt(run1)
        r2 = _make_dummy_receipt(run2)
        storage.summary_deliveries.save_receipt(r1)
        storage.summary_deliveries.save_receipt(r2)

        # Only run1 has an outbox delivery
        d1 = _make_dummy_delivery(org_id, run1)
        storage.summary_deliveries.save_delivery(d1)

        unreg = storage.summary_deliveries.list_unregistered_terminal_receipts(org_id)
        assert len(unreg) == 1
        assert unreg[0].run_id == run2

