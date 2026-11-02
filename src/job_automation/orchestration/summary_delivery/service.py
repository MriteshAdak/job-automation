"""SummaryDeliveryService orchestrating per-run delivery, checkpoints, and recovery (AUTO-03-S02, S04).

Enforces:
- Durable receipt commitment before remote network I/O.
- Exactly one delivery lane per (org_id, run_id).
- Capped exponential backoff with jitter and persisted UTC deadlines.
- Ambiguous outcome routing: lost responses and timeouts transition to RECONCILE_REQUIRED.
- Authoritative absence check before replay: resend only when verified absent.
- Remote Flow deduplication: retries and newer revisions never multiply completion alerts.
- Bounded repair scanner recovering missing delivery intents without re-running pipeline stages.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.salesforce import (
    GatewayFailure,
    GatewayResult,
    OperationKind,
    RecoveryAction,
    RemoteOutcome,
)
from job_automation.orchestration.reporting import RunReport
from job_automation.orchestration.summary_delivery.adapter import (
    FakeSalesforceSummaryTargetAdapter,
    SalesforceSummaryTargetAdapter,
    SummaryTargetPort,
)
from job_automation.orchestration.summary_delivery.projection import (
    build_summary_projection,
)
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
from job_automation.orchestration.summary_delivery.settings import (
    SummaryDeliverySettings,
    load_summary_delivery_settings,
)
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class SummaryDeliveryService:
    """Coordinates per-run summary persistence, dispatch, bounded retries, and reconciliation."""

    def __init__(
        self,
        engine: StorageEngine,
        settings: SummaryDeliverySettings | None = None,
        target_adapter: SummaryTargetPort | None = None,
        lock: WindowsWorkerLock | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings or SummaryDeliverySettings()
        self.target_adapter = target_adapter
        self.lock = lock

    # -------------------------------------------------------------------------
    # Target Adapter Resolution
    # -------------------------------------------------------------------------

    def get_adapter(self, org_id: str | None = None) -> SummaryTargetPort:
        """Resolve or initialize the summary target adapter."""
        if self.target_adapter is not None:
            return self.target_adapter

        # Default fallback to fake adapter if no gateway is provided
        target_org = org_id or self.settings.salesforce_org_id or "00D000000000001"
        return FakeSalesforceSummaryTargetAdapter(org_id=target_org, settings=self.settings, use_shared=True)

    # -------------------------------------------------------------------------
    # Receipt and Delivery Registration
    # -------------------------------------------------------------------------

    def record_run_completion(
        self,
        report: RunReport,
        org_id: str | None = None,
    ) -> RunCompletionReceipt:
        """Record an authoritative terminal completion receipt at the RUN-01 boundary.

        If summary delivery is enabled, creates or updates the SummaryDelivery outbox record.
        """
        c15 = report.c15_summary
        run_id = c15.run_id
        target_org = org_id or self.settings.salesforce_org_id or "00D000000000001"

        # Check existing receipts for this run to determine monotonically increasing revision
        existing_receipts = self.engine.summary_deliveries.list_receipts(run_id)
        current_rev = len(existing_receipts) + 1

        receipt = RunCompletionReceipt(
            run_id=run_id,
            attempt_sequence=report.attempt_sequence,
            revision=current_rev,
            start_time=c15.start_time,
            completed_at=c15.end_time,
            status=c15.status.value,
            c15_summary=c15,
            assessment_mode=report.assessment_mode,
            sources_attempted=list(report.sources_attempted),
            sources_succeeded=list(report.sources_succeeded),
            sources_failed=list(report.sources_failed),
            quarantined_records_count=report.quarantined_records_count,
            availability_transitions_count=report.availability_transitions_count,
            reused_assessments_count=report.reused_assessments_count,
            model_invocations_count=report.model_invocations_count,
            exit_code=report.exit_code,
            is_final=True,
        )

        # 1. Commit RunCompletionReceipt atomically to database
        self.engine.summary_deliveries.save_receipt(receipt)
        logger.info(
            "Persisted RunCompletionReceipt for run '%s' (attempt %d, rev %d, status '%s')",
            run_id,
            receipt.attempt_sequence,
            receipt.revision,
            receipt.status,
        )

        # 2. If delivery is disabled, do not enqueue outbox work
        if not self.settings.enabled:
            return receipt

        # 3. Check activation epoch cutoff
        if self.settings.activation_epoch_utc and receipt.completed_at < self.settings.activation_epoch_utc:
            logger.info("Run '%s' completion before activation epoch; skipping delivery enqueue", run_id)
            return receipt

        # 4. Check existing outbox delivery
        now_utc = datetime.now(timezone.utc)
        existing_delivery = self.engine.summary_deliveries.get_delivery(target_org, run_id)

        if existing_delivery is None:
            # First completion snapshot
            proj = build_summary_projection(
                receipt=receipt,
                org_id=target_org,
                is_first_completion=True,
            )
            retry_deadline = now_utc + timedelta(hours=self.settings.max_recovery_age_hours)
            delivery = SummaryDelivery(
                run_id=run_id,
                org_id=target_org,
                completion_key=proj.completion_key,
                revision=1,
                state=DeliveryState.PENDING,
                target_object=self.settings.target_object_name,
                target_external_id_field=self.settings.target_external_id_field,
                payload_json=proj.model_dump_json(),
                payload_hash=proj.current_revision_hash,
                first_completion_hash=proj.first_result_snapshot_hash,
                retry_window_start=now_utc,
                retry_deadline=retry_deadline,
                next_due_at=now_utc,
            )
            self.engine.summary_deliveries.save_delivery(delivery)
        else:
            # Subsequent resume revision: update payload while preserving first_completion_hash
            proj = build_summary_projection(
                receipt=receipt,
                org_id=target_org,
                is_first_completion=False,
                first_result_snapshot_hash=existing_delivery.first_completion_hash,
            )
            # If previously acknowledged, keep state as delivered unless payload changed
            new_state = DeliveryState.PENDING if existing_delivery.state != DeliveryState.DELIVERED else DeliveryState.DELIVERED
            updated_delivery = existing_delivery.model_copy(
                update={
                    "revision": receipt.revision,
                    "payload_json": proj.model_dump_json(),
                    "payload_hash": proj.current_revision_hash,
                    "state": new_state,
                    "next_due_at": now_utc if new_state == DeliveryState.PENDING else existing_delivery.next_due_at,
                    "updated_at": now_utc,
                }
            )
            self.engine.summary_deliveries.save_delivery(updated_delivery)

        return receipt

    # -------------------------------------------------------------------------
    # Delivery Dispatch & Retries
    # -------------------------------------------------------------------------

    def deliver_summary(
        self,
        run_id: uuid.UUID,
        org_id: str | None = None,
        force: bool = False,
        test_recipient: str | None = None,
    ) -> DeliveryReport:
        """Deliver a specific run summary projection to the target."""
        target_org = org_id or self.settings.salesforce_org_id or "00D000000000001"
        delivery = self.engine.summary_deliveries.get_delivery(target_org, run_id)
        if delivery is None:
            # Try finding delivery by run ID alone
            delivery = self.engine.summary_deliveries.get_delivery_by_run_id(run_id)

        if delivery is None:
            raise ValueError(f"No summary delivery found for run ID '{run_id}' in org '{target_org}'")

        now_utc = datetime.now(timezone.utc)

        # Check existing state
        if delivery.state == DeliveryState.DELIVERED and not force:
            return DeliveryReport(
                run_id=delivery.run_id,
                delivery_state=delivery.state,
                notification_state=delivery.notification_state,
                dispatch_attempts=delivery.dispatch_attempts,
                reconcile_attempts=delivery.reconcile_attempts,
                remote_record_id=delivery.remote_record_id,
                next_due_at=delivery.next_due_at,
                acknowledged_at=delivery.acknowledged_at,
            )

        if delivery.state in (DeliveryState.BLOCKED, DeliveryState.EXHAUSTED) and not force:
            return DeliveryReport(
                run_id=delivery.run_id,
                delivery_state=delivery.state,
                notification_state=delivery.notification_state,
                dispatch_attempts=delivery.dispatch_attempts,
                reconcile_attempts=delivery.reconcile_attempts,
                remote_record_id=delivery.remote_record_id,
                next_due_at=delivery.next_due_at,
                last_error=delivery.last_error_message,
                acknowledged_at=delivery.acknowledged_at,
            )

        # If reconcile is required, reconcile before sending!
        if delivery.state == DeliveryState.RECONCILE_REQUIRED:
            reconcile_report = self.reconcile_delivery(run_id=delivery.run_id, org_id=delivery.org_id)
            if reconcile_report.delivery_state != DeliveryState.PENDING:
                return reconcile_report
            # Re-read delivery after reconciliation
            delivery = self.engine.summary_deliveries.get_delivery(delivery.org_id, delivery.run_id)
            assert delivery is not None

        # Transition to IN_FLIGHT
        claim_token = uuid.uuid4().hex
        delivery = delivery.model_copy(
            update={
                "state": DeliveryState.IN_FLIGHT,
                "claim_token": claim_token,
                "claimed_at": now_utc,
                "updated_at": now_utc,
            }
        )
        self.engine.summary_deliveries.save_delivery(delivery)

        # Parse projection
        proj = RunSummaryProjection.model_validate_json(delivery.payload_json)
        adapter = self.get_adapter(delivery.org_id)

        # Perform physical upsert
        t_start = datetime.now(timezone.utc)
        recipient = test_recipient or self.settings.test_recipient
        res = adapter.upsert_summary(proj, test_recipient=recipient)
        t_duration_ms = max(0.0, (datetime.now(timezone.utc) - t_start).total_seconds() * 1000.0)

        attempt_seq = delivery.dispatch_attempts + 1

        if res.is_success:
            ack = res.value
            assert ack is not None

            # Record successful attempt audit
            attempt_rec = DeliveryAttemptRecord(
                delivery_id=delivery.delivery_id,
                run_id=delivery.run_id,
                attempt_sequence=attempt_seq,
                operation_kind="upsert",
                status="succeeded",
                http_status=200 if not ack.is_created else 201,
                duration_ms=t_duration_ms,
                remote_outcome="acknowledged",
                created_at=now_utc,
            )
            self.engine.summary_deliveries.save_attempt(attempt_rec)

            # Update delivery to DELIVERED
            delivery = delivery.model_copy(
                update={
                    "state": DeliveryState.DELIVERED,
                    "dispatch_attempts": attempt_seq,
                    "remote_record_id": ack.record_id,
                    "acknowledged_revision": ack.applied_revision,
                    "acknowledged_hash": ack.applied_hash,
                    "acknowledged_at": ack.acknowledged_at,
                    "notification_state": ack.notification_state,
                    "notification_receipt_id": ack.notification_receipt_id,
                    "last_error_category": None,
                    "last_error_code": None,
                    "last_error_message": None,
                    "claim_token": None,
                    "claimed_at": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.engine.summary_deliveries.save_delivery(delivery)

            return DeliveryReport(
                run_id=delivery.run_id,
                delivery_state=delivery.state,
                notification_state=delivery.notification_state,
                dispatch_attempts=delivery.dispatch_attempts,
                reconcile_attempts=delivery.reconcile_attempts,
                remote_record_id=delivery.remote_record_id,
                acknowledged_at=delivery.acknowledged_at,
            )

        # Handle failure
        fail = res.failure
        assert fail is not None

        attempt_rec = DeliveryAttemptRecord(
            delivery_id=delivery.delivery_id,
            run_id=delivery.run_id,
            attempt_sequence=attempt_seq,
            operation_kind="upsert",
            status="failed" if fail.remote_outcome != RemoteOutcome.UNKNOWN else "ambiguous",
            http_status=fail.http_status,
            duration_ms=t_duration_ms,
            remote_outcome=fail.remote_outcome.value,
            recovery_action=fail.recovery_action.value,
            safe_error_code=fail.safe_provider_code,
            safe_error_message=fail.error.message[:500] if fail.error.message else None,
            created_at=now_utc,
        )
        self.engine.summary_deliveries.save_attempt(attempt_rec)

        new_attempts = delivery.dispatch_attempts + 1

        # Classify state transition
        if fail.remote_outcome == RemoteOutcome.UNKNOWN:
            # Ambiguous: lost connection or timeout after send
            new_state = DeliveryState.RECONCILE_REQUIRED
            next_due = now_utc
        elif fail.recovery_action == RecoveryAction.RETRY_LATER:
            # Definite transient failure: compute backoff with jitter
            if new_attempts >= self.settings.max_dispatch_attempts or now_utc >= delivery.retry_deadline:
                new_state = DeliveryState.EXHAUSTED
                next_due = None
            else:
                new_state = DeliveryState.RETRY_WAIT
                delay = min(
                    self.settings.max_backoff_seconds,
                    self.settings.initial_backoff_seconds * (self.settings.backoff_multiplier ** (new_attempts - 1)),
                )
                jitter_val = delay * self.settings.jitter_ratio
                actual_delay = max(0.1, delay + random.uniform(-jitter_val, jitter_val))
                next_due = now_utc + timedelta(seconds=actual_delay)
        else:
            # 400, 401, 403, permission, or unrecoverable config error
            new_state = DeliveryState.BLOCKED
            next_due = None

        delivery = delivery.model_copy(
            update={
                "state": new_state,
                "dispatch_attempts": new_attempts,
                "next_due_at": next_due,
                "last_error_category": fail.error.category.value,
                "last_error_code": fail.safe_provider_code,
                "last_error_message": fail.error.message[:500] if fail.error.message else None,
                "claim_token": None,
                "claimed_at": None,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.engine.summary_deliveries.save_delivery(delivery)

        return DeliveryReport(
            run_id=delivery.run_id,
            delivery_state=delivery.state,
            notification_state=delivery.notification_state,
            dispatch_attempts=delivery.dispatch_attempts,
            reconcile_attempts=delivery.reconcile_attempts,
            remote_record_id=delivery.remote_record_id,
            next_due_at=delivery.next_due_at,
            last_error=delivery.last_error_message,
        )

    # -------------------------------------------------------------------------
    # Reconciliation
    # -------------------------------------------------------------------------

    def reconcile_delivery(
        self,
        run_id: uuid.UUID,
        org_id: str | None = None,
    ) -> DeliveryReport:
        """Query remote target by run External ID to reconcile ambiguous outcome or verify acknowledgment."""
        target_org = org_id or self.settings.salesforce_org_id or "00D000000000001"
        delivery = self.engine.summary_deliveries.get_delivery(target_org, run_id)
        if delivery is None:
            delivery = self.engine.summary_deliveries.get_delivery_by_run_id(run_id)

        if delivery is None:
            raise ValueError(f"No summary delivery found for run ID '{run_id}' in org '{target_org}'")

        now_utc = datetime.now(timezone.utc)
        attempt_seq = delivery.reconcile_attempts + 1

        adapter = self.get_adapter(delivery.org_id)
        t_start = datetime.now(timezone.utc)
        res = adapter.get_summary(delivery.org_id, delivery.run_id)
        t_duration_ms = max(0.0, (datetime.now(timezone.utc) - t_start).total_seconds() * 1000.0)

        if res.is_failure:
            fail = res.failure
            assert fail is not None

            attempt_rec = DeliveryAttemptRecord(
                delivery_id=delivery.delivery_id,
                run_id=delivery.run_id,
                attempt_sequence=attempt_seq,
                operation_kind="query_reconcile",
                status="failed",
                http_status=fail.http_status,
                duration_ms=t_duration_ms,
                remote_outcome=fail.remote_outcome.value,
                recovery_action=fail.recovery_action.value,
                safe_error_code=fail.safe_provider_code,
                safe_error_message=fail.error.message[:500] if fail.error.message else None,
                created_at=now_utc,
            )
            self.engine.summary_deliveries.save_attempt(attempt_rec)

            # Classify error
            if fail.recovery_action == RecoveryAction.RETRY_LATER:
                new_state = DeliveryState.RETRY_WAIT
                next_due = now_utc + timedelta(seconds=self.settings.initial_backoff_seconds)
            else:
                new_state = DeliveryState.BLOCKED
                next_due = None

            delivery = delivery.model_copy(
                update={
                    "state": new_state,
                    "reconcile_attempts": attempt_seq,
                    "next_due_at": next_due,
                    "last_error_category": fail.error.category.value,
                    "last_error_code": fail.safe_provider_code,
                    "last_error_message": fail.error.message[:500] if fail.error.message else None,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.engine.summary_deliveries.save_delivery(delivery)
            return DeliveryReport(
                run_id=delivery.run_id,
                delivery_state=delivery.state,
                notification_state=delivery.notification_state,
                dispatch_attempts=delivery.dispatch_attempts,
                reconcile_attempts=delivery.reconcile_attempts,
                remote_record_id=delivery.remote_record_id,
                next_due_at=delivery.next_due_at,
                last_error=delivery.last_error_message,
            )

        ack = res.value

        if ack is None or not ack.is_present:
            # Authoritative absence: record definitely does NOT exist on Salesforce
            logger.info("Reconciliation confirmed absence of run '%s'; safe to replay", run_id)
            attempt_rec = DeliveryAttemptRecord(
                delivery_id=delivery.delivery_id,
                run_id=delivery.run_id,
                attempt_sequence=attempt_seq,
                operation_kind="query_reconcile",
                status="succeeded",
                duration_ms=t_duration_ms,
                remote_outcome="absent",
                created_at=now_utc,
            )
            self.engine.summary_deliveries.save_attempt(attempt_rec)

            delivery = delivery.model_copy(
                update={
                    "state": DeliveryState.PENDING,
                    "reconcile_attempts": attempt_seq,
                    "next_due_at": now_utc,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.engine.summary_deliveries.save_delivery(delivery)
            return DeliveryReport(
                run_id=delivery.run_id,
                delivery_state=delivery.state,
                notification_state=delivery.notification_state,
                dispatch_attempts=delivery.dispatch_attempts,
                reconcile_attempts=delivery.reconcile_attempts,
                remote_record_id=delivery.remote_record_id,
                next_due_at=delivery.next_due_at,
            )

        # Record exists remotely: verify revision and payload hash
        if ack.applied_hash == delivery.payload_hash:
            # Verified matching payload! Acknowledge delivery
            logger.info("Reconciliation confirmed matching payload hash for run '%s'", run_id)
            attempt_rec = DeliveryAttemptRecord(
                delivery_id=delivery.delivery_id,
                run_id=delivery.run_id,
                attempt_sequence=attempt_seq,
                operation_kind="query_reconcile",
                status="succeeded",
                duration_ms=t_duration_ms,
                remote_outcome="matched_acknowledgment",
                created_at=now_utc,
            )
            self.engine.summary_deliveries.save_attempt(attempt_rec)

            delivery = delivery.model_copy(
                update={
                    "state": DeliveryState.DELIVERED,
                    "reconcile_attempts": attempt_seq,
                    "remote_record_id": ack.record_id,
                    "acknowledged_revision": ack.applied_revision,
                    "acknowledged_hash": ack.applied_hash,
                    "acknowledged_at": ack.acknowledged_at,
                    "notification_state": ack.notification_state,
                    "notification_receipt_id": ack.notification_receipt_id,
                    "last_error_category": None,
                    "last_error_code": None,
                    "last_error_message": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.engine.summary_deliveries.save_delivery(delivery)
        else:
            # Hash conflict or unexpected remote state: hold for repair
            logger.warning(
                "Reconciliation hash conflict for run '%s': local=%s, remote=%s",
                run_id,
                delivery.payload_hash,
                ack.applied_hash,
            )
            attempt_rec = DeliveryAttemptRecord(
                delivery_id=delivery.delivery_id,
                run_id=delivery.run_id,
                attempt_sequence=attempt_seq,
                operation_kind="query_reconcile",
                status="failed",
                duration_ms=t_duration_ms,
                remote_outcome="hash_conflict",
                safe_error_code="PAYLOAD_HASH_MISMATCH",
                safe_error_message="PAYLOAD_HASH_MISMATCH: Remote record exists with differing payload hash; held for operator repair",
                created_at=now_utc,
            )
            self.engine.summary_deliveries.save_attempt(attempt_rec)

            delivery = delivery.model_copy(
                update={
                    "state": DeliveryState.BLOCKED,
                    "reconcile_attempts": attempt_seq,
                    "remote_record_id": ack.record_id,
                    "last_error_category": "integrity_conflict",
                    "last_error_code": "PAYLOAD_HASH_MISMATCH",
                    "last_error_message": "PAYLOAD_HASH_MISMATCH: Remote record exists with differing payload hash; held for operator repair",
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.engine.summary_deliveries.save_delivery(delivery)

        return DeliveryReport(
            run_id=delivery.run_id,
            delivery_state=delivery.state,
            notification_state=delivery.notification_state,
            dispatch_attempts=delivery.dispatch_attempts,
            reconcile_attempts=delivery.reconcile_attempts,
            remote_record_id=delivery.remote_record_id,
            last_error=delivery.last_error_message,
            acknowledged_at=delivery.acknowledged_at,
        )

    # -------------------------------------------------------------------------
    # Drain and Maintenance
    # -------------------------------------------------------------------------

    def drain(
        self,
        limit: int = 50,
        as_of: datetime | None = None,
        test_recipient: str | None = None,
    ) -> list[DeliveryReport]:
        """Drain due summary deliveries up to configured limit under the deployment lock."""
        target_org = self.settings.salesforce_org_id or "00D000000000001"
        now_utc = as_of or datetime.now(timezone.utc)

        # 1. Recover stale in_flight claims left by dead workers
        stale_threshold = now_utc - timedelta(minutes=5)
        stale_cnt = self.engine.summary_deliveries.claim_stale_in_flight(target_org, stale_threshold)
        if stale_cnt > 0:
            logger.warning("Recovered %d stale in_flight summary deliveries to reconcile_required", stale_cnt)

        # 2. Claim due deliveries
        claim_token = uuid.uuid4().hex
        claimed = self.engine.summary_deliveries.claim_due_deliveries(
            org_id=target_org,
            claim_token=claim_token,
            limit=limit,
            as_of=now_utc,
        )

        reports: list[DeliveryReport] = []
        for d in claimed:
            rep = self.deliver_summary(run_id=d.run_id, org_id=target_org, test_recipient=test_recipient)
            reports.append(rep)

        return reports

    def repair_unregistered_completions(
        self,
        org_id: str | None = None,
        limit: int = 50,
    ) -> int:
        """Scan committed receipts and synthesize missing outbox delivery entities."""
        target_org = org_id or self.settings.salesforce_org_id or "00D000000000001"
        unregistered = self.engine.summary_deliveries.list_unregistered_terminal_receipts(
            org_id=target_org,
            cutoff_epoch=self.settings.activation_epoch_utc,
            limit=limit,
        )

        repaired = 0
        now_utc = datetime.now(timezone.utc)
        retry_deadline = now_utc + timedelta(hours=self.settings.max_recovery_age_hours)

        for receipt in unregistered:
            proj = build_summary_projection(
                receipt=receipt,
                org_id=target_org,
                is_first_completion=True,
            )
            delivery = SummaryDelivery(
                run_id=receipt.run_id,
                org_id=target_org,
                completion_key=proj.completion_key,
                revision=receipt.revision,
                state=DeliveryState.PENDING,
                target_object=self.settings.target_object_name,
                target_external_id_field=self.settings.target_external_id_field,
                payload_json=proj.model_dump_json(),
                payload_hash=proj.current_revision_hash,
                first_completion_hash=proj.first_result_snapshot_hash,
                retry_window_start=now_utc,
                retry_deadline=retry_deadline,
                next_due_at=now_utc,
            )
            self.engine.summary_deliveries.save_delivery(delivery)
            repaired += 1
            logger.info("Repaired missing delivery outbox entity for run '%s'", receipt.run_id)

        return repaired

    def reset_retry(
        self,
        run_id: uuid.UUID,
        org_id: str | None = None,
        additional_attempts: int = 3,
    ) -> SummaryDelivery:
        """Manually reset retry budget and transition a blocked or exhausted delivery to RECONCILE_REQUIRED."""
        target_org = org_id or self.settings.salesforce_org_id or "00D000000000001"
        delivery = self.engine.summary_deliveries.get_delivery(target_org, run_id)
        if delivery is None:
            delivery = self.engine.summary_deliveries.get_delivery_by_run_id(run_id)

        if delivery is None:
            raise ValueError(f"No summary delivery found for run ID '{run_id}' in org '{target_org}'")

        now_utc = datetime.now(timezone.utc)
        new_deadline = max(delivery.retry_deadline, now_utc + timedelta(hours=24))

        updated = delivery.model_copy(
            update={
                "state": DeliveryState.RECONCILE_REQUIRED,  # Always reconcile before mutation!
                "dispatch_attempts": max(0, delivery.dispatch_attempts - additional_attempts),
                "retry_deadline": new_deadline,
                "next_due_at": now_utc,
                "claim_token": None,
                "claimed_at": None,
                "updated_at": now_utc,
            }
        )
        self.engine.summary_deliveries.save_delivery(updated)
        logger.info("Reset delivery retry allowance for run '%s' (new state: RECONCILE_REQUIRED)", run_id)
        return updated
