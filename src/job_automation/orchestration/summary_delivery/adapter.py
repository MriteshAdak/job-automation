"""Target adapters and protocols for SF-09 summary delivery (AUTO-03-S03).

Provides:
- SummaryTargetPort: Interface boundary for delivering summaries and reading acknowledgments.
- SalesforceSummaryTargetAdapter: Production adapter using SalesforceGatewayV2.
- FakeSalesforceSummaryTargetAdapter: Stateful in-memory target verifying remote Flow
  deduplication semantics, lost responses, and outage recovery.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.salesforce import (
    AttemptSummary,
    GatewayFailure,
    GatewayResult,
    GetRecordRequest,
    GetRecordResult,
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
    UpsertRequest,
    UpsertResult,
)
from job_automation.orchestration.summary_delivery.records import (
    NotificationState,
    RunSummaryProjection,
    TargetAcknowledgment,
)
from job_automation.orchestration.summary_delivery.settings import SummaryDeliverySettings

logger = logging.getLogger(__name__)


@runtime_checkable
class SummaryTargetPort(Protocol):
    """Boundary protocol for delivering run summary projections to the remote target."""

    def upsert_summary(
        self,
        projection: RunSummaryProjection,
        test_recipient: str | None = None,
    ) -> GatewayResult[TargetAcknowledgment]:
        """Upsert summary projection by run External ID."""
        ...

    def get_summary(
        self,
        org_id: str,
        run_id: uuid.UUID,
    ) -> GatewayResult[TargetAcknowledgment]:
        """Read summary record by run External ID for reconciliation."""
        ...


class SalesforceSummaryTargetAdapter(SummaryTargetPort):
    """Production implementation of SummaryTargetPort backed by SalesforceGatewayV2."""

    def __init__(
        self,
        gateway: SalesforceGatewayV2,
        settings: SummaryDeliverySettings,
    ) -> None:
        self.gateway = gateway
        self.settings = settings

    def _map_projection_to_fields(
        self,
        projection: RunSummaryProjection,
        test_recipient: str | None = None,
    ) -> dict[str, Any]:
        """Map RunSummaryProjection to typed machine-owned Salesforce fields."""
        fields: dict[str, Any] = {
            self.settings.target_external_id_field: str(projection.run_id),
            "Name": projection.headline[:80],
            "Pipeline_Status__c": projection.pipeline_status,
            "Start_Time__c": projection.start_time.isoformat(),
            "End_Time__c": projection.end_time.isoformat(),
            "Duration_Seconds__c": projection.duration_seconds,
            "Headline__c": projection.headline,
            "Summary_Text__c": projection.summary_text,
            "Source_Postings_Count__c": projection.source_postings_count,
            "Canonical_Jobs_New__c": projection.canonical_jobs_new,
            "Canonical_Jobs_Updated__c": projection.canonical_jobs_updated,
            "Canonical_Jobs_Duplicate__c": projection.canonical_jobs_duplicate,
            "Eligible_Count__c": projection.eligible_count,
            "Review_Count__c": projection.review_count,
            "Rejected_Count__c": projection.rejected_count,
            "Sync_Succeeded__c": projection.sync_succeeded,
            "Sync_Failed__c": projection.sync_failed,
            "Quarantined_Count__c": projection.quarantined_count,
            "Sources_Attempted__c": ", ".join(projection.sources_attempted),
            "Sources_Succeeded__c": ", ".join(projection.sources_succeeded),
            "Sources_Failed__c": ", ".join(projection.sources_failed),
            "Revision__c": projection.revision,
            "Payload_Hash__c": projection.current_revision_hash,
            "First_Completion_Key__c": projection.completion_key,
            "First_Payload_Hash__c": projection.first_result_snapshot_hash,
        }

        if projection.error_summary:
            fields["Error_Summary__c"] = projection.error_summary
        if projection.pending_work_summary:
            fields["Pending_Work_Summary__c"] = projection.pending_work_summary

        recipient = test_recipient or self.settings.test_recipient

        if projection.is_first_completion:
            # First completion triggers notification Flow
            fields["Notification_Status__c"] = "pending"
            if recipient:
                fields["Notification_Recipient__c"] = recipient
        else:
            # Subsequent resume revisions do not rearm the Flow
            fields["Notification_Status__c"] = "updated"

        return fields

    def upsert_summary(
        self,
        projection: RunSummaryProjection,
        test_recipient: str | None = None,
    ) -> GatewayResult[TargetAcknowledgment]:
        """Dispatch summary upsert by External ID."""
        fields = self._map_projection_to_fields(projection, test_recipient=test_recipient)
        req = UpsertRequest(
            object_name=self.settings.target_object_name,
            external_id_field=self.settings.target_external_id_field,
            external_id_value=str(projection.run_id),
            fields=fields,
            replay_safe=False,  # Replay is governed by AUTO-03 reconciliation, not gateway
        )

        res = self.gateway.upsert_by_external_id(req)
        if res.is_failure:
            return GatewayResult.fail(res.failure, attempts=res.attempts)

        upsert_val = res.value
        assert upsert_val is not None

        ack = TargetAcknowledgment(
            org_id=projection.org_id,
            record_id=upsert_val.record_id,
            run_id=projection.run_id,
            applied_revision=projection.revision,
            applied_hash=projection.current_revision_hash,
            completion_key=projection.completion_key,
            is_created=upsert_val.created,
            notification_state=NotificationState.PENDING if projection.is_first_completion else NotificationState.NONE,
            acknowledged_at=upsert_val.acknowledged_at,
        )
        return GatewayResult.success(ack, attempts=res.attempts)

    def get_summary(
        self,
        org_id: str,
        run_id: uuid.UUID,
    ) -> GatewayResult[TargetAcknowledgment]:
        """Read back summary by External ID to verify remote state."""
        req = GetRecordRequest(
            object_name=self.settings.target_object_name,
            external_id_field=self.settings.target_external_id_field,
            external_id_value=str(run_id),
            fields=[
                "Id",
                self.settings.target_external_id_field,
                "Revision__c",
                "Payload_Hash__c",
                "First_Completion_Key__c",
                "Notification_Status__c",
                "Notification_Receipt_Id__c",
            ],
        )

        res = self.gateway.get_record(req)
        if res.is_failure:
            fail = res.failure
            assert fail is not None
            # Check if 404 not found
            if fail.http_status == 404 or fail.error.category == ErrorCategory.VALIDATION:
                absent_ack = TargetAcknowledgment(
                    is_present=False,
                    org_id=org_id,
                    record_id="",
                    run_id=run_id,
                    applied_revision=0,
                    applied_hash="",
                    completion_key=f"{org_id}:{run_id}",
                    is_created=False,
                    notification_state=NotificationState.NONE,
                )
                return GatewayResult.success(absent_ack, attempts=res.attempts)
            return GatewayResult.fail(fail, attempts=res.attempts)

        rec_val = res.value
        assert rec_val is not None

        fields = rec_val.fields
        applied_rev = int(fields.get("Revision__c", 1))
        applied_hash = str(fields.get("Payload_Hash__c", ""))
        comp_key = str(fields.get("First_Completion_Key__c", f"{org_id}:{run_id}"))

        notif_raw = str(fields.get("Notification_Status__c", "")).lower()
        if notif_raw == "confirmed":
            notif_state = NotificationState.CONFIRMED
        elif notif_raw == "failed":
            notif_state = NotificationState.FAILED
        elif notif_raw == "pending":
            notif_state = NotificationState.PENDING
        else:
            notif_state = NotificationState.NONE

        ack = TargetAcknowledgment(
            org_id=org_id,
            record_id=rec_val.record_id,
            run_id=run_id,
            applied_revision=applied_rev,
            applied_hash=applied_hash,
            completion_key=comp_key,
            is_created=False,
            notification_state=notif_state,
            notification_receipt_id=fields.get("Notification_Receipt_Id__c"),
            acknowledged_at=datetime.now(timezone.utc),
        )
        return GatewayResult.success(ack, attempts=res.attempts)


class FakeSalesforceSummaryTargetAdapter(SummaryTargetPort):
    """In-memory fake target simulating the SF-09 remote object and notification Flow.

    Key verification guarantees:
    - External ID upsert store keyed by run_id.
    - Flow trigger execution: records remote alerts and assigns Notification_Receipt_Id__c.
    - Repeated upserts or retries for the SAME run_id DO NOT multiply remote completion alerts!
    - Revisions on resume DO NOT generate secondary completion alerts!
    - Supports scriptable lost responses, notification service outages, and transport errors.
    """

    _shared_records: dict[str, dict[str, Any]] = {}
    _shared_alerts: list[dict[str, Any]] = []

    @classmethod
    def clear_shared(cls) -> None:
        """Clear process-wide shared records (useful for test isolation)."""
        cls._shared_records.clear()
        cls._shared_alerts.clear()

    def __init__(
        self,
        org_id: str = "00D000000000001",
        settings: SummaryDeliverySettings | None = None,
        use_shared: bool = False,
    ) -> None:
        self.org_id = org_id
        self.settings = settings or SummaryDeliverySettings(enabled=True, salesforce_org_id=org_id)
        self.use_shared = use_shared

        # In-memory remote records: run_id_str -> record dict
        if use_shared:
            self.records = self._shared_records
            self.alerts_sent = self._shared_alerts
        else:
            self.records = {}
            self.alerts_sent = []

        # Alert tracking
        self.remote_alert_count: int = len(self.alerts_sent)

        # Transmission metrics
        self.physical_upsert_count: int = 0
        self.physical_get_count: int = 0

        # Scriptable fault simulation
        self.simulate_lost_response_on_upsert: bool = False
        self.simulate_notification_service_outage: bool = False
        self.simulate_permission_denied: bool = False
        self.simulate_server_error: bool = False
        self.simulate_rate_limit: bool = False

    def upsert_summary(
        self,
        projection: RunSummaryProjection,
        test_recipient: str | None = None,
    ) -> GatewayResult[TargetAcknowledgment]:
        self.physical_upsert_count += 1
        run_key = str(projection.run_id)

        # Simulate permission failure
        if self.simulate_permission_denied:
            fail = GatewayFailure(
                error=ClassifiedError.permission("Insufficient access rights on object Run_Summary__c"),
                http_status=403,
                operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
                remote_outcome=RemoteOutcome.NOT_SENT,
                recovery_action=RecoveryAction.REAUTHORIZE,
                safe_provider_code="CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY",
            )
            return GatewayResult.fail(fail)

        # Simulate rate limit
        if self.simulate_rate_limit:
            fail = GatewayFailure(
                error=ClassifiedError.transient_capacity("API rate limit exceeded"),
                http_status=429,
                operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
                remote_outcome=RemoteOutcome.NOT_SENT,
                recovery_action=RecoveryAction.RETRY_LATER,
                safe_provider_code="REQUEST_LIMIT_EXCEEDED",
            )
            return GatewayResult.fail(fail)

        # Simulate server error
        if self.simulate_server_error:
            fail = GatewayFailure(
                error=ClassifiedError.transient_network("Salesforce service temporarily unavailable"),
                http_status=503,
                operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
                remote_outcome=RemoteOutcome.NOT_SENT,
                recovery_action=RecoveryAction.RETRY_LATER,
            )
            return GatewayResult.fail(fail)

        # Process record creation / update
        is_created = run_key not in self.records
        if is_created:
            record_id = f"a05{uuid.uuid4().hex[:15]}"
            record = {
                "Id": record_id,
                self.settings.target_external_id_field: run_key,
                "First_Completion_Key__c": projection.completion_key,
                "First_Payload_Hash__c": projection.first_result_snapshot_hash,
                "Notification_Receipt_Id__c": None,
                "Notification_Status__c": "none",
            }
            self.records[run_key] = record
        else:
            record = self.records[run_key]
            record_id = record["Id"]

        # Update latest fields
        record.update(
            {
                "Name": projection.headline[:80],
                "Pipeline_Status__c": projection.pipeline_status,
                "Start_Time__c": projection.start_time.isoformat(),
                "End_Time__c": projection.end_time.isoformat(),
                "Duration_Seconds__c": projection.duration_seconds,
                "Headline__c": projection.headline,
                "Summary_Text__c": projection.summary_text,
                "Source_Postings_Count__c": projection.source_postings_count,
                "Canonical_Jobs_New__c": projection.canonical_jobs_new,
                "Canonical_Jobs_Updated__c": projection.canonical_jobs_updated,
                "Canonical_Jobs_Duplicate__c": projection.canonical_jobs_duplicate,
                "Eligible_Count__c": projection.eligible_count,
                "Review_Count__c": projection.review_count,
                "Rejected_Count__c": projection.rejected_count,
                "Sync_Succeeded__c": projection.sync_succeeded,
                "Sync_Failed__c": projection.sync_failed,
                "Quarantined_Count__c": projection.quarantined_count,
                "Sources_Attempted__c": ", ".join(projection.sources_attempted),
                "Sources_Succeeded__c": ", ".join(projection.sources_succeeded),
                "Sources_Failed__c": ", ".join(projection.sources_failed),
                "Revision__c": projection.revision,
                "Payload_Hash__c": projection.current_revision_hash,
            }
        )

        recipient = test_recipient or self.settings.test_recipient

        # Simulate SF-09 Flow Execution & Deduplication Gate:
        # A notification is dispatched IF AND ONLY IF:
        # 1. This is the first completion (is_first_completion is True), AND
        # 2. No notification receipt exists yet for this record.
        # Retries or updates for an already-notified run NEVER fire a second alert!
        notif_state = NotificationState.NONE
        receipt_id = record.get("Notification_Receipt_Id__c")

        if projection.is_first_completion and receipt_id is None:
            if self.simulate_notification_service_outage:
                # Flow failed to deliver notification
                record["Notification_Status__c"] = "failed"
                notif_state = NotificationState.FAILED
            else:
                # Flow delivered notification successfully!
                new_receipt = str(uuid.uuid4())
                record["Notification_Status__c"] = "confirmed"
                record["Notification_Receipt_Id__c"] = new_receipt
                record["Notification_Recipient__c"] = recipient or "system_default"
                self.remote_alert_count += 1
                self.alerts_sent.append(
                    {
                        "run_id": run_key,
                        "recipient": recipient or "system_default",
                        "headline": projection.headline,
                        "receipt_id": new_receipt,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                notif_state = NotificationState.CONFIRMED
                receipt_id = new_receipt
        else:
            # Retried upsert or newer revision on resume: Flow conditions not met
            notif_raw = record.get("Notification_Status__c", "none")
            if notif_raw == "confirmed":
                notif_state = NotificationState.CONFIRMED
            elif notif_raw == "failed":
                notif_state = NotificationState.FAILED
            else:
                notif_state = NotificationState.NONE

        # Simulate lost response (commit succeeded remotely, but network timed out before client received ACK)
        if self.simulate_lost_response_on_upsert:
            self.simulate_lost_response_on_upsert = False
            fail = GatewayFailure(
                error=ClassifiedError.transient_network("Connection reset by peer after write commit (lost response)"),
                http_status=None,
                operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
                remote_outcome=RemoteOutcome.UNKNOWN,
                recovery_action=RecoveryAction.RECONCILE,
                attempts=[
                    AttemptSummary(
                        attempt_number=1,
                        purpose="upsert_summary",
                        duration_ms=250.0,
                        uncertain_transmission=True,
                    )
                ],
            )
            return GatewayResult.fail(fail)

        ack = TargetAcknowledgment(
            org_id=self.org_id,
            record_id=record_id,
            run_id=projection.run_id,
            applied_revision=projection.revision,
            applied_hash=projection.current_revision_hash,
            completion_key=projection.completion_key,
            is_created=is_created,
            notification_state=notif_state,
            notification_receipt_id=receipt_id,
            acknowledged_at=datetime.now(timezone.utc),
        )
        return GatewayResult.success(ack)

    def get_summary(
        self,
        org_id: str,
        run_id: uuid.UUID,
    ) -> GatewayResult[TargetAcknowledgment]:
        self.physical_get_count += 1
        run_key = str(run_id)

        if run_key not in self.records:
            absent_ack = TargetAcknowledgment(
                is_present=False,
                org_id=self.org_id,
                record_id="",
                run_id=run_id,
                applied_revision=0,
                applied_hash="",
                completion_key=f"{self.org_id}:{run_id}",
                is_created=False,
                notification_state=NotificationState.NONE,
            )
            return GatewayResult.success(absent_ack)

        record = self.records[run_key]
        notif_raw = record.get("Notification_Status__c", "none")
        if notif_raw == "confirmed":
            notif_state = NotificationState.CONFIRMED
        elif notif_raw == "failed":
            notif_state = NotificationState.FAILED
        elif notif_raw == "pending":
            notif_state = NotificationState.PENDING
        else:
            notif_state = NotificationState.NONE

        ack = TargetAcknowledgment(
            org_id=self.org_id,
            record_id=record["Id"],
            run_id=run_id,
            applied_revision=record.get("Revision__c", 1),
            applied_hash=record.get("Payload_Hash__c", ""),
            completion_key=record.get("First_Completion_Key__c", f"{org_id}:{run_id}"),
            is_created=False,
            notification_state=notif_state,
            notification_receipt_id=record.get("Notification_Receipt_Id__c"),
            acknowledged_at=datetime.now(timezone.utc),
        )
        return GatewayResult.success(ack)
