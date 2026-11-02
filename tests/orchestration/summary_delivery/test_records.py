"""Unit tests for AUTO-03 contracts, schemas, and records."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.summary_delivery.records import (
    DeliveryAttemptRecord,
    DeliveryReport,
    DeliveryState,
    NotificationState,
    RunCompletionReceipt,
    RunSummaryProjection,
    SummaryDelivery,
    TargetAcknowledgment,
)
from job_automation.orchestration.summary_delivery.settings import SummaryDeliverySettings


def _make_dummy_c15(run_id: uuid.UUID) -> RunSummary:
    now = datetime.now(timezone.utc)
    return RunSummary(
        run_id=run_id,
        start_time=now,
        end_time=now,
        status=RunStatus.SUCCESS,
        source_counts={"arbeitnow": 10},
        source_postings_count=10,
        canonical_jobs_new=3,
        canonical_jobs_updated=1,
        canonical_jobs_duplicate=6,
        eligible_count=2,
        review_count=1,
        rejected_count=0,
        sync_operations_succeeded=2,
        sync_operations_failed=0,
    )


class TestSummaryDeliveryRecords:
    def test_run_completion_receipt_hash_stability(self) -> None:
        run_id = uuid.uuid4()
        c15 = _make_dummy_c15(run_id)
        now = datetime.now(timezone.utc)

        receipt1 = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=c15,
            sources_attempted=["arbeitnow"],
            sources_succeeded=["arbeitnow"],
        )
        receipt2 = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=c15,
            sources_attempted=["arbeitnow"],
            sources_succeeded=["arbeitnow"],
        )
        assert receipt1.receipt_hash != ""
        assert receipt1.receipt_hash == receipt2.receipt_hash

    def test_run_completion_receipt_json_roundtrip(self) -> None:
        run_id = uuid.uuid4()
        c15 = _make_dummy_c15(run_id)
        now = datetime.now(timezone.utc)

        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=1,
            revision=1,
            start_time=now,
            completed_at=now,
            status="success",
            c15_summary=c15,
            sources_attempted=["arbeitnow"],
            sources_succeeded=["arbeitnow"],
            reused_assessments_count=5,
            model_invocations_count=2,
        )
        json_data = receipt.model_dump_json()
        loaded = RunCompletionReceipt.model_validate_json(json_data)
        assert loaded.run_id == run_id
        assert loaded.receipt_hash == receipt.receipt_hash
        assert loaded.reused_assessments_count == 5

    def test_summary_delivery_settings_validation(self) -> None:
        settings = SummaryDeliverySettings(
            enabled=True,
            salesforce_org_id="00D000000000001",
            max_dispatch_attempts=3,
            initial_backoff_seconds=1.5,
        )
        assert settings.enabled is True
        assert settings.max_dispatch_attempts == 3

        # Invalid target object name fails validation
        with pytest.raises(ValidationError):
            SummaryDeliverySettings(target_object_name="Invalid Object Name with Spaces!")

        # Invalid external ID field fails validation
        with pytest.raises(ValidationError):
            SummaryDeliverySettings(target_external_id_field="123_invalid_id")

    def test_target_acknowledgment_model(self) -> None:
        run_id = uuid.uuid4()
        ack = TargetAcknowledgment(
            org_id="00D000000000001",
            record_id="a05000000000001",
            run_id=run_id,
            applied_revision=1,
            applied_hash="abc123hash",
            completion_key=f"00D000000000001:{run_id}",
            is_created=True,
            notification_state=NotificationState.CONFIRMED,
            notification_receipt_id="rec_999",
        )
        assert ack.record_id == "a05000000000001"
        assert ack.notification_state == NotificationState.CONFIRMED
        assert ack.notification_receipt_id == "rec_999"

    def test_delivery_attempt_record(self) -> None:
        deliv_id = uuid.uuid4()
        run_id = uuid.uuid4()
        att = DeliveryAttemptRecord(
            delivery_id=deliv_id,
            run_id=run_id,
            attempt_sequence=1,
            operation_kind="upsert",
            status="succeeded",
            http_status=201,
            duration_ms=120.5,
            remote_outcome="acknowledged",
        )
        assert att.delivery_id == deliv_id
        assert att.http_status == 201
        assert att.status == "succeeded"

