"""Target adapter and remote notification deduplication tests (T09, T13)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.summary_delivery.adapter import (
    FakeSalesforceSummaryTargetAdapter,
    SalesforceSummaryTargetAdapter,
)
from job_automation.orchestration.summary_delivery.projection import (
    build_summary_projection,
)
from job_automation.orchestration.summary_delivery.records import (
    NotificationState,
    RunCompletionReceipt,
    RunSummaryProjection,
)
from job_automation.orchestration.summary_delivery.settings import SummaryDeliverySettings
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


def _make_dummy_projection(
    run_id: uuid.UUID,
    revision: int = 1,
    is_first_completion: bool = True,
    first_hash: str | None = None,
) -> RunSummaryProjection:
    now = datetime.now(timezone.utc)
    c15 = RunSummary(
        run_id=run_id,
        start_time=now,
        end_time=now,
        status=RunStatus.SUCCESS,
        source_counts={"arbeitnow": 20},
        source_postings_count=20,
        canonical_jobs_new=4,
    )
    receipt = RunCompletionReceipt(
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
    return build_summary_projection(
        receipt,
        org_id="00D000000000001",
        is_first_completion=is_first_completion,
        first_result_snapshot_hash=first_hash,
    )


class TestTargetAdapter:
    def test_salesforce_summary_target_adapter_upsert_and_get(self) -> None:
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")
        settings = SummaryDeliverySettings(enabled=True, salesforce_org_id="00D000000000001")
        adapter = SalesforceSummaryTargetAdapter(gateway=gateway, settings=settings)

        run_id = uuid.uuid4()
        proj = _make_dummy_projection(run_id, revision=1, is_first_completion=True)

        # 1. Upsert summary
        res = adapter.upsert_summary(proj, test_recipient="test_user@example.com")
        assert res.is_success
        ack = res.value
        assert ack is not None
        assert ack.run_id == run_id
        assert ack.is_created is True
        assert ack.applied_revision == 1
        assert ack.notification_state == NotificationState.PENDING

        # Verify gateway was called with replay_safe=False
        assert len(gateway.upsert_requests) == 1
        assert gateway.upsert_requests[0].replay_safe is False
        assert gateway.upsert_requests[0].object_name == "Run_Summary__c"
        assert gateway.upsert_requests[0].external_id_field == "Run_Id__c"

        # 2. Read back summary for reconciliation
        get_res = adapter.get_summary(org_id="00D000000000001", run_id=run_id)
        assert get_res.is_success
        read_ack = get_res.value
        assert read_ack is not None
        assert read_ack.run_id == run_id
        assert read_ack.record_id == ack.record_id
        assert read_ack.applied_revision == 1

    def test_salesforce_summary_target_adapter_absent_record(self) -> None:
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")
        settings = SummaryDeliverySettings(enabled=True, salesforce_org_id="00D000000000001")
        adapter = SalesforceSummaryTargetAdapter(gateway=gateway, settings=settings)

        absent_id = uuid.uuid4()
        res = adapter.get_summary(org_id="00D000000000001", run_id=absent_id)
        assert res.is_success
        assert res.value is not None
        assert res.value.is_present is False  # Authoritatively absent

    def test_t09_fake_adapter_remote_alert_deduplication(self) -> None:
        """T09: Retried delivery does not multiply remote completion alerts."""
        adapter = FakeSalesforceSummaryTargetAdapter(org_id="00D000000000001")
        run_id = uuid.uuid4()
        proj = _make_dummy_projection(run_id, revision=1, is_first_completion=True)

        # 1. First completion upsert -> Flow fires, alert sent
        res1 = adapter.upsert_summary(proj, test_recipient="test_user@example.com")
        assert res1.is_success
        ack1 = res1.value
        assert ack1 is not None
        assert ack1.notification_state == NotificationState.CONFIRMED
        assert ack1.notification_receipt_id is not None
        assert adapter.remote_alert_count == 1
        assert len(adapter.alerts_sent) == 1

        # 2. Retry identical delivery (e.g. timeout on client side or scheduled replay)
        res2 = adapter.upsert_summary(proj, test_recipient="test_user@example.com")
        assert res2.is_success
        ack2 = res2.value
        assert ack2 is not None
        # Record is updated, but Flow DOES NOT re-alert!
        assert adapter.remote_alert_count == 1
        assert len(adapter.alerts_sent) == 1

        # 3. Third identical retry
        res3 = adapter.upsert_summary(proj, test_recipient="test_user@example.com")
        assert res3.is_success
        assert adapter.remote_alert_count == 1
        assert len(adapter.alerts_sent) == 1

    def test_t09_subsequent_resume_revision_does_not_fire_alert(self) -> None:
        """T09: Later revisions update latest-result fields silently without rearming Flow."""
        adapter = FakeSalesforceSummaryTargetAdapter(org_id="00D000000000001")
        run_id = uuid.uuid4()

        # Initial run (revision 1)
        proj1 = _make_dummy_projection(run_id, revision=1, is_first_completion=True)
        res1 = adapter.upsert_summary(proj1, test_recipient="test_user@example.com")
        assert res1.is_success
        assert adapter.remote_alert_count == 1
        initial_hash = proj1.first_result_snapshot_hash

        # Resumed run (revision 2)
        proj2 = _make_dummy_projection(
            run_id,
            revision=2,
            is_first_completion=False,
            first_hash=initial_hash,
        )
        res2 = adapter.upsert_summary(proj2, test_recipient="test_user@example.com")
        assert res2.is_success
        ack2 = res2.value
        assert ack2 is not None
        assert ack2.applied_revision == 2

        # Alert count strictly remains 1!
        assert adapter.remote_alert_count == 1
        assert len(adapter.alerts_sent) == 1

    def test_t09_distinct_run_has_its_own_alert(self) -> None:
        """A genuinely new run with its own UUID receives its own alert."""
        adapter = FakeSalesforceSummaryTargetAdapter(org_id="00D000000000001")

        run1 = uuid.uuid4()
        run2 = uuid.uuid4()

        proj1 = _make_dummy_projection(run1, revision=1, is_first_completion=True)
        proj2 = _make_dummy_projection(run2, revision=1, is_first_completion=True)

        adapter.upsert_summary(proj1)
        assert adapter.remote_alert_count == 1

        adapter.upsert_summary(proj2)
        assert adapter.remote_alert_count == 2

    def test_t13_notification_service_outage(self) -> None:
        """T13: When remote Flow fails, record is delivered but notification is failed."""
        adapter = FakeSalesforceSummaryTargetAdapter(org_id="00D000000000001")
        adapter.simulate_notification_service_outage = True

        run_id = uuid.uuid4()
        proj = _make_dummy_projection(run_id, revision=1, is_first_completion=True)

        res = adapter.upsert_summary(proj)
        assert res.is_success
        ack = res.value
        assert ack is not None
        assert ack.notification_state == NotificationState.FAILED
        assert adapter.remote_alert_count == 0  # 0 alerts sent during outage

    def test_t13_permission_failure(self) -> None:
        """T13: 403 permission error returns classified failure."""
        adapter = FakeSalesforceSummaryTargetAdapter(org_id="00D000000000001")
        adapter.simulate_permission_denied = True

        run_id = uuid.uuid4()
        proj = _make_dummy_projection(run_id, revision=1)

        res = adapter.upsert_summary(proj)
        assert res.is_failure
        fail = res.failure
        assert fail is not None
        assert fail.http_status == 403
        assert fail.recovery_action.value == "reauthorize"

    def test_lost_response_simulation(self) -> None:
        """Simulates committed write with client timeout returning RemoteOutcome.UNKNOWN."""
        adapter = FakeSalesforceSummaryTargetAdapter(org_id="00D000000000001")
        adapter.simulate_lost_response_on_upsert = True

        run_id = uuid.uuid4()
        proj = _make_dummy_projection(run_id, revision=1)

        res = adapter.upsert_summary(proj)
        assert res.is_failure
        fail = res.failure
        assert fail is not None
        assert fail.remote_outcome.value == "unknown"
        assert fail.recovery_action.value == "reconcile"

        # Even though client received unknown, the record committed remotely!
        read_res = adapter.get_summary(org_id="00D000000000001", run_id=run_id)
        assert read_res.is_success
        assert read_res.value is not None
