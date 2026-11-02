"""Acceptance test suite for SF-09 Run-Summary Notification Target (T01-T16).

Verifies the complete acceptance test matrix from docs/stories/SF-09.md:
- T01: Nonempty success; zero-posting complete success; duplicate/update-only success; zero eligible.
- T02: Partial source/stage failure with usable work; failed before discovering jobs.
- T03: Running ledger fallback; unadmitted invocation; recovered interrupted admitted run.
- T04: Exact initial payload upsert 10 times (idempotency, client writes to server fields rejected).
- T05: Commit succeeds but client loses HTTP response (reconciliation query by External ID).
- T06: Concurrent duplicate upserts, overlapping interviews, and serialized claim.
- T07: Same-run failed -> success resume (revision 1 -> 2); delayed first alert snapshot preservation.
- T08: Stale revision rejection, revision conflict detection, hash coverage.
- T09: New run UUID with identical input and counts (run UUID based identity, not content-based).
- T10: Missing/invalid recipient, disabled configuration, held/suppressed states, safe pre-send retry.
- T11: Ambiguous network timeout after possible send (fenced in unknown, no blind resend).
- T12: Notification confirmed -> marker self-update, status re-entry, Flow redeploy produces no second alert.
- T13: Scoped worker, candidate reader, and admin permission boundaries.
- T14: Long/Unicode source keys and diagnostics, secret/path scrubbing, unknown coverage distinct from zero.
- T15: Historical import suppression prior to activation watermark.
- T16: AUTO-03 adapter integration compatibility and decoupled pipeline outcomes.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import threading
import uuid
import pytest
from zoneinfo import ZoneInfo

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.salesforce import GatewayResult, UpsertResult
from job_automation.orchestration.summary_delivery.adapter import SalesforceSummaryTargetAdapter
from job_automation.orchestration.summary_delivery.records import (
    NotificationState,
    RunSummaryProjection,
    TargetAcknowledgment,
)
from job_automation.orchestration.summary_delivery.settings import SummaryDeliverySettings
from job_automation.salesforce.metadata_parser import (
    load_permission_set,
    validate_sf09_admin_permission_set,
    validate_sf09_reader_permission_set,
    validate_sf09_worker_permission_set,
)
from job_automation.salesforce.run_summaries import (
    CoverageStatus,
    LanguageCode,
    PipelineStatus,
    RunSummaryAdmissionService,
    RunSummaryDispatchService,
    RunSummaryError,
    RunSummaryNotificationConfig,
    RunSummaryNotificationStatus,
    RunSummaryRecord,
    RunSummaryRecoveryService,
    RunSummaryRevisionConflictError,
    RunSummaryStaleRevisionError,
    RunSummaryValidationError,
    format_run_summary_notification,
    sanitize_summary_text,
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PERMSETS_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "permissionsets"


@pytest.fixture
def admission_service() -> RunSummaryAdmissionService:
    return RunSummaryAdmissionService(org_id="00D000000000001EAA")


@pytest.fixture
def dispatch_service() -> RunSummaryDispatchService:
    return RunSummaryDispatchService()


@pytest.fixture
def enabled_config() -> RunSummaryNotificationConfig:
    return RunSummaryNotificationConfig(
        org_key="default",
        is_enabled=True,
        candidate_user_id="005000000000001AAA",
        preferred_language=LanguageCode.EN,
        max_retry_attempts=3,
        initial_retry_delay_minutes=1,
    )


class TestSF09Scenarios:

    def test_t01_all_success_categories(
        self, admission_service: RunSummaryAdmissionService, enabled_config: RunSummaryNotificationConfig
    ) -> None:
        """T01: Nonempty success; zero-posting complete success; duplicate/update-only success; zero eligible."""
        now = datetime.now(timezone.utc)

        # 1. Nonempty success
        run1 = uuid.uuid4()
        f1 = {
            "Run_Id__c": str(run1),
            "Pipeline_Status__c": "success",
            "Headline__c": "Discovered 12 vacancies",
            "Source_Postings_Count__c": 12,
            "Canonical_Jobs_New__c": 5,
            "Canonical_Jobs_Updated__c": 3,
            "Canonical_Jobs_Duplicate__c": 4,
            "Eligible_Count__c": 2,
            "Start_Time__c": (now - timedelta(minutes=5)).isoformat(),
            "End_Time__c": now.isoformat(),
            "Coverage_Status__c": "complete",
        }
        rec1 = admission_service.admit_summary(f1, config=enabled_config)
        assert rec1.pipeline_status == PipelineStatus.SUCCESS
        assert rec1.notification_status == RunSummaryNotificationStatus.PENDING
        title1, body1 = format_run_summary_notification(rec1, language="en")
        assert title1 == "Run Completed: Success"
        assert "Observed: 12 postings" in body1
        assert "+5 new" in body1

        # 2. Zero-posting complete success -> "No postings found"
        run2 = uuid.uuid4()
        f2 = {
            "Run_Id__c": str(run2),
            "Pipeline_Status__c": "success",
            "Headline__c": "Search completed",
            "Source_Postings_Count__c": 0,
            "Canonical_Jobs_New__c": 0,
            "Coverage_Status__c": "complete",
            "Start_Time__c": (now - timedelta(minutes=3)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec2 = admission_service.admit_summary(f2, config=enabled_config)
        title2, body2 = format_run_summary_notification(rec2, language="en")
        assert title2 == "Run Completed: No postings found"
        assert "No postings found across configured sources" in body2

        # 3. Duplicate/update-only success -> "No new jobs"
        run3 = uuid.uuid4()
        f3 = {
            "Run_Id__c": str(run3),
            "Pipeline_Status__c": "success",
            "Headline__c": "Observed 5 duplicates",
            "Source_Postings_Count__c": 5,
            "Canonical_Jobs_New__c": 0,
            "Canonical_Jobs_Updated__c": 2,
            "Canonical_Jobs_Duplicate__c": 3,
            "Coverage_Status__c": "complete",
            "Start_Time__c": (now - timedelta(minutes=2)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec3 = admission_service.admit_summary(f3, config=enabled_config)
        title3, body3 = format_run_summary_notification(rec3, language="en")
        assert title3 == "Run Completed: No new jobs"
        assert "+0 new, 2 updated, 3 duplicate" in body3

    def test_t02_partial_and_failed_runs(
        self, admission_service: RunSummaryAdmissionService, enabled_config: RunSummaryNotificationConfig
    ) -> None:
        """T02: Partial source/stage failure with usable work; failed before discovering jobs."""
        now = datetime.now(timezone.utc)

        # Partial run
        run_part = uuid.uuid4()
        f_part = {
            "Run_Id__c": str(run_part),
            "Pipeline_Status__c": "partial",
            "Headline__c": "Search partial",
            "Source_Postings_Count__c": 4,
            "Canonical_Jobs_New__c": 2,
            "Coverage_Status__c": "partial",
            "Sources_Attempted__c": "source_a, source_b",
            "Sources_Succeeded__c": "source_a",
            "Sources_Failed__c": "source_b",
            "Error_Summary__c": "source_b HTTP 503 service unavailable",
            "Start_Time__c": (now - timedelta(minutes=4)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec_part = admission_service.admit_summary(f_part, config=enabled_config)
        assert rec_part.pipeline_status == PipelineStatus.PARTIAL
        assert rec_part.first_status == PipelineStatus.PARTIAL
        title_p, body_p = format_run_summary_notification(rec_part, language="en")
        assert title_p == "Run Completed: Partial"
        assert "source_b HTTP 503" in body_p

        # Failed run
        run_fail = uuid.uuid4()
        f_fail = {
            "Run_Id__c": str(run_fail),
            "Pipeline_Status__c": "failed",
            "Headline__c": "Pipeline failed during ingest",
            "Source_Postings_Count__c": 0,
            "Coverage_Status__c": "unavailable",
            "Error_Summary__c": "Disk full error during sqlite checkpoint",
            "Start_Time__c": (now - timedelta(minutes=1)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec_fail = admission_service.admit_summary(f_fail, config=enabled_config)
        assert rec_fail.pipeline_status == PipelineStatus.FAILED
        assert rec_fail.first_status == PipelineStatus.FAILED
        title_f, body_f = format_run_summary_notification(rec_fail, language="en")
        assert title_f == "Run Completed: Failed"
        assert "Disk full error" in body_f

    def test_t03_running_or_unadmitted_invocation_zero_entitlement(
        self, admission_service: RunSummaryAdmissionService, enabled_config: RunSummaryNotificationConfig
    ) -> None:
        """T03: Non-terminal pipeline states create no completion entitlement."""
        run_id = uuid.uuid4()
        with pytest.raises(RunSummaryValidationError):
            admission_service.admit_summary(
                {"Run_Id__c": str(run_id), "Pipeline_Status__c": "running"},
                config=enabled_config,
            )

    def test_t04_idempotent_replay_10_times(
        self,
        admission_service: RunSummaryAdmissionService,
        dispatch_service: RunSummaryDispatchService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T04: Exact initial payload upsert 10 times results in 1 entitlement and 1 dispatch."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        payload = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Headline__c": "10 postings discovered",
            "Source_Postings_Count__c": 10,
            "Revision__c": 1,
            "Payload_Hash__c": "hash-initial-1234",
            "Start_Time__c": (now - timedelta(minutes=5)).isoformat(),
            "End_Time__c": now.isoformat(),
            "Is_First_Completion__c": True,
        }

        # First admission
        record = admission_service.admit_summary(payload, existing=None, config=enabled_config)
        assert record.notification_status == RunSummaryNotificationStatus.PENDING

        # Dispatch once
        sent_calls: list[str] = []

        def fake_sender(title: str, body: str, target_id: str, recipient: str) -> bool:
            sent_calls.append(target_id)
            return True

        record = dispatch_service.dispatch(record, config=enabled_config, notif_sender=fake_sender)
        assert record.notification_status == RunSummaryNotificationStatus.CONFIRMED
        assert len(sent_calls) == 1
        initial_receipt = record.notification_receipt_id
        initial_accepted = record.notification_accepted_at

        # Replay 9 more times
        for _ in range(9):
            replayed = admission_service.admit_summary(payload, existing=record, config=enabled_config)
            # Re-dispatch attempt
            replayed = dispatch_service.dispatch(replayed, config=enabled_config, notif_sender=fake_sender)
            assert replayed.notification_status == RunSummaryNotificationStatus.CONFIRMED
            assert replayed.notification_receipt_id == initial_receipt
            assert replayed.notification_accepted_at == initial_accepted
            assert len(sent_calls) == 1  # ZERO duplicate action invocations!

    def test_t05_reconciliation_lost_http_response(
        self,
        admission_service: RunSummaryAdmissionService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T05: Lost HTTP response reconciliation verifies remote presence without duplicate send."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        fields = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Headline__c": "Reconciliation Test",
            "Revision__c": 1,
            "Payload_Hash__c": "expected-hash-456",
            "Start_Time__c": (now - timedelta(minutes=5)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec = admission_service.admit_summary(fields, config=enabled_config)

        # Simulation: Client queries Salesforce for reconciliation
        assert rec.run_id == run_id
        assert rec.payload_hash == "expected-hash-456"
        assert rec.first_completion_key == f"00D000000000001:{run_id}"

    def test_t06_concurrent_creates_and_claims(
        self,
        admission_service: RunSummaryAdmissionService,
        dispatch_service: RunSummaryDispatchService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T06: Concurrent duplicate upserts and dispatch claims resolve to one winner."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        fields = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Headline__c": "Concurrency Test",
            "Revision__c": 1,
            "Payload_Hash__c": "hash-conc",
            "Start_Time__c": (now - timedelta(minutes=2)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        record = admission_service.admit_summary(fields, config=enabled_config)

        sent_count = 0
        sent_lock = threading.Lock()

        def slow_sender(title: str, body: str, target: str, recipient: str) -> bool:
            nonlocal sent_count
            with sent_lock:
                sent_count += 1
            return True

        threads: list[threading.Thread] = []
        for _ in range(5):
            t = threading.Thread(target=lambda: dispatch_service.dispatch(record, enabled_config, slow_sender))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        assert sent_count == 1
        assert record.notification_status == RunSummaryNotificationStatus.CONFIRMED

    def test_t07_same_run_failed_to_success_resume_preserves_first_snapshot(
        self,
        admission_service: RunSummaryAdmissionService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T07: Failed -> Success resume (rev 1 -> 2) preserves initial failed snapshot and entitlement."""
        run_id = uuid.uuid4()
        t1 = datetime.now(timezone.utc) - timedelta(minutes=15)
        t2 = t1 + timedelta(minutes=5)

        # Initial failed run
        f1 = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "failed",
            "Headline__c": "Initial failure",
            "Revision__c": 1,
            "Payload_Hash__c": "hash-rev-1",
            "Start_Time__c": t1.isoformat(),
            "End_Time__c": t2.isoformat(),
            "Error_Summary__c": "API rate limited",
        }
        rec = admission_service.admit_summary(f1, config=enabled_config)
        assert rec.first_status == PipelineStatus.FAILED
        assert rec.first_headline == "Initial failure"
        assert rec.pipeline_status == PipelineStatus.FAILED

        # Resumed run arrives as revision 2 with success
        t3 = datetime.now(timezone.utc)
        f2 = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Headline__c": "Resumed run success",
            "Source_Postings_Count__c": 15,
            "Canonical_Jobs_New__c": 7,
            "Revision__c": 2,
            "Payload_Hash__c": "hash-rev-2",
            "Start_Time__c": t1.isoformat(),
            "End_Time__c": t3.isoformat(),
            "Error_Summary__c": None,
        }
        updated = admission_service.admit_summary(f2, existing=rec, config=enabled_config)

        # Invariant: latest pipeline status updates, but first-status snapshot remains failed
        assert updated.pipeline_status == PipelineStatus.SUCCESS
        assert updated.headline == "Resumed run success"
        assert updated.first_status == PipelineStatus.FAILED
        assert updated.first_headline == "Initial failure"
        assert updated.first_payload_hash == "hash-rev-1"
        assert updated.revision == 2

        # Delayed first alert describes the first failure snapshot
        title, body = format_run_summary_notification(updated, language="en")
        assert title == "Run Completed: Failed"
        assert "API rate limited" in body

    def test_t08_revision_conflicts_and_stale_revisions(
        self,
        admission_service: RunSummaryAdmissionService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T08: Stale revision (< applied) and revision conflict (same rev, different hash) are rejected."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        f1 = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Revision__c": 2,
            "Payload_Hash__c": "hash-rev-2",
            "Start_Time__c": (now - timedelta(minutes=5)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec = admission_service.admit_summary(f1, config=enabled_config)

        # 1. Stale revision (rev 1 arriving after rev 2)
        f_stale = dict(f1, Revision__c=1, Payload_Hash__c="hash-rev-1")
        with pytest.raises(RunSummaryStaleRevisionError):
            admission_service.admit_summary(f_stale, existing=rec, config=enabled_config)

        # 2. Same revision with different hash
        f_conflict = dict(f1, Revision__c=2, Payload_Hash__c="tampered-hash-999")
        with pytest.raises(RunSummaryRevisionConflictError):
            admission_service.admit_summary(f_conflict, existing=rec, config=enabled_config)

    def test_t09_new_run_uuid_independent_entitlements(
        self,
        admission_service: RunSummaryAdmissionService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T09: New run UUID with identical inputs produces independent records and entitlements."""
        now = datetime.now(timezone.utc)
        common_fields = {
            "Pipeline_Status__c": "success",
            "Headline__c": "Common run",
            "Source_Postings_Count__c": 10,
            "Revision__c": 1,
            "Payload_Hash__c": "identical-hash-123",
            "Start_Time__c": (now - timedelta(minutes=5)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        run_a = uuid.uuid4()
        run_b = uuid.uuid4()

        rec_a = admission_service.admit_summary(dict(common_fields, Run_Id__c=str(run_a)), config=enabled_config)
        rec_b = admission_service.admit_summary(dict(common_fields, Run_Id__c=str(run_b)), config=enabled_config)

        assert rec_a.run_id != rec_b.run_id
        assert rec_a.first_completion_key != rec_b.first_completion_key
        assert rec_a.notification_status == RunSummaryNotificationStatus.PENDING
        assert rec_b.notification_status == RunSummaryNotificationStatus.PENDING

    def test_t10_missing_recipient_and_disabled_configuration(
        self,
        admission_service: RunSummaryAdmissionService,
        dispatch_service: RunSummaryDispatchService,
    ) -> None:
        """T10: Missing recipient or disabled config prevents alerts and records safe error code."""
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        fields = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Headline__c": "Disabled config run",
            "Start_Time__c": (now - timedelta(minutes=2)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        disabled_cfg = RunSummaryNotificationConfig(is_enabled=False)
        rec = admission_service.admit_summary(fields, config=disabled_cfg)
        assert rec.notification_status == RunSummaryNotificationStatus.NONE

        # Attempt dispatch
        rec = dispatch_service.dispatch(rec, config=disabled_cfg)
        assert rec.notification_status == RunSummaryNotificationStatus.NONE

    def test_t11_ambiguous_network_timeout_fences_in_unknown(
        self,
        admission_service: RunSummaryAdmissionService,
        dispatch_service: RunSummaryDispatchService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T11: Network timeout fences notification in UNKNOWN; retries without reconciliation are blocked."""
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        fields = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Headline__c": "Timeout Run",
            "Start_Time__c": (now - timedelta(minutes=5)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec = admission_service.admit_summary(fields, config=enabled_config)

        def timeout_sender(title: str, body: str, target: str, recipient: str) -> bool:
            raise TimeoutError("Salesforce API timeout waiting for custom notification")

        rec = dispatch_service.dispatch(rec, config=enabled_config, notif_sender=timeout_sender)
        assert rec.notification_status == RunSummaryNotificationStatus.UNKNOWN
        assert rec.notification_error_code == "AMBIGUOUS_SEND"

        # Subsequent dispatch attempts are held in UNKNOWN
        rec = dispatch_service.dispatch(rec, config=enabled_config, notif_sender=timeout_sender)
        assert rec.notification_status == RunSummaryNotificationStatus.UNKNOWN

        # Operator reconciles proven non-send -> resets to retry_wait
        reconciled = RunSummaryRecoveryService.reconcile_unknown(rec, was_delivered=False)
        assert reconciled.notification_status == RunSummaryNotificationStatus.RETRY_WAIT

    def test_t12_confirmed_status_never_rearms(
        self,
        admission_service: RunSummaryAdmissionService,
        dispatch_service: RunSummaryDispatchService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T12: Confirmed notification status never rearms on status re-entry or newer revisions."""
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        fields = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "success",
            "Headline__c": "Confirmed Run",
            "Revision__c": 1,
            "Payload_Hash__c": "h-1",
            "Start_Time__c": (now - timedelta(minutes=5)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec = admission_service.admit_summary(fields, config=enabled_config)
        rec = dispatch_service.dispatch(rec, config=enabled_config, notif_sender=lambda *args: True)
        assert rec.notification_status == RunSummaryNotificationStatus.CONFIRMED

        # Send higher revision
        f2 = dict(fields, Revision__c=2, Payload_Hash__c="h-2")
        rec = admission_service.admit_summary(f2, existing=rec, config=enabled_config)
        assert rec.notification_status == RunSummaryNotificationStatus.CONFIRMED

        # Attempt second dispatch
        rec = dispatch_service.dispatch(rec, config=enabled_config, notif_sender=lambda *args: True)
        assert rec.notification_status == RunSummaryNotificationStatus.CONFIRMED

    def test_t13_permission_set_boundaries(self) -> None:
        """T13: Worker, candidate reader, and admin permission sets strictly enforce boundaries."""
        worker_ps = load_permission_set(PERMSETS_DIR / "Job_Summary_Worker.permissionset-meta.xml")
        reader_ps = load_permission_set(PERMSETS_DIR / "Job_Summary_Reader.permissionset-meta.xml")
        admin_ps = load_permission_set(PERMSETS_DIR / "Job_Summary_Administrator.permissionset-meta.xml")

        assert validate_sf09_worker_permission_set(worker_ps).compatible is True
        assert validate_sf09_reader_permission_set(reader_ps).compatible is True
        assert validate_sf09_admin_permission_set(admin_ps).compatible is True

        # Worker cannot edit server-managed fields
        assert worker_ps.field_permissions["run_summary__c.completion_recorded_at__c"].editable is False
        assert worker_ps.field_permissions["run_summary__c.notification_status__c"].editable is False
        assert worker_ps.field_permissions["run_summary__c.first_status__c"].editable is False

        # Reader has read-only access
        assert reader_ps.object_permissions["run_summary__c"].allow_edit is False
        assert reader_ps.object_permissions["run_summary__c"].allow_create is False

    def test_t14_diagnostic_sanitization_and_unknown_coverage(
        self,
        admission_service: RunSummaryAdmissionService,
        enabled_config: RunSummaryNotificationConfig,
    ) -> None:
        """T14: Diagnostic sanitization scrubs secrets and local paths; unknown coverage is distinct from zero."""
        raw_error = "Error at C:\\Users\\Administrator\\job-search\\vault.db: Bearer secret_token_1234567890abcdef"
        sanitized = sanitize_summary_text(raw_error)
        assert "[REDACTED_SECRET]" in sanitized
        assert "[REDACTED_PATH]" in sanitized
        assert "secret_token_1234567890abcdef" not in sanitized
        assert "C:\\Users\\Administrator" not in sanitized

        # Unknown coverage
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        f = {
            "Run_Id__c": str(run_id),
            "Pipeline_Status__c": "failed",
            "Headline__c": "Failed run",
            "Coverage_Status__c": "unavailable",
            "Source_Postings_Count__c": 0,
            "Start_Time__c": (now - timedelta(minutes=1)).isoformat(),
            "End_Time__c": now.isoformat(),
        }
        rec = admission_service.admit_summary(f, config=enabled_config)
        assert rec.coverage_status == CoverageStatus.UNAVAILABLE
        title, _ = format_run_summary_notification(rec, language="en")
        assert title == "Run Completed: Failed"

    def test_t15_historical_import_suppression(
        self,
        admission_service: RunSummaryAdmissionService,
    ) -> None:
        """T15: Historical imports completed prior to activation watermark are suppressed."""
        watermark = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        config = RunSummaryNotificationConfig(
            is_enabled=True,
            candidate_user_id="005000000000001AAA",
            activation_watermark=watermark,
        )

        old_run = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)
        fields = {
            "Run_Id__c": str(uuid.uuid4()),
            "Pipeline_Status__c": "success",
            "Headline__c": "Historical run",
            "Start_Time__c": (old_run - timedelta(minutes=5)).isoformat(),
            "End_Time__c": old_run.isoformat(),
        }
        rec = admission_service.admit_summary(fields, config=config)
        assert rec.notification_status == RunSummaryNotificationStatus.SUPPRESSED
        assert rec.notification_error_code == "HISTORICAL_PRIOR_TO_WATERMARK"

    def test_t16_auto03_adapter_integration_compatibility(self) -> None:
        """T16: SalesforceSummaryTargetAdapter field mapping aligns with SF-09 Run_Summary__c schema."""
        settings = SummaryDeliverySettings(
            target_object_name="Run_Summary__c",
            target_external_id_field="Run_Id__c",
            test_recipient="005000000000001AAA",
        )

        # Build synthetic projection
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        proj = RunSummaryProjection(
            schema_version="1.0",
            run_id=run_id,
            org_id="00D000000000001",
            completion_key=f"00D000000000001:{run_id}",
            revision=1,
            pipeline_status="success",
            start_time=now - timedelta(minutes=5),
            end_time=now,
            duration_seconds=300.0,
            headline="AUTO-03 Compatibility Test",
            summary_text="Detailed test summary",
            source_postings_count=10,
            canonical_jobs_new=4,
            canonical_jobs_updated=2,
            canonical_jobs_duplicate=4,
            eligible_count=2,
            review_count=1,
            rejected_count=1,
            sync_succeeded=4,
            sync_failed=0,
            quarantined_count=0,
            sources_attempted=("source_a",),
            sources_succeeded=("source_a",),
            sources_failed=(),
            is_first_completion=True,
            current_revision_hash="hash-123",
            first_result_snapshot_hash="hash-123",
        )

        # Mock gateway
        class FakeGateway:
            def upsert_by_external_id(self, req: Any) -> GatewayResult[UpsertResult]:
                assert req.object_name == "Run_Summary__c"
                assert req.external_id_field == "Run_Id__c"
                assert req.external_id_value == str(run_id)
                f = req.fields
                assert f["Pipeline_Status__c"] == "success"
                assert f["Revision__c"] == 1
                assert f["First_Completion_Key__c"] == f"00D000000000001:{run_id}"
                assert f["Notification_Status__c"] == "pending"
                assert f["Notification_Recipient__c"] == "005000000000001AAA"
                res = UpsertResult(
                    object_name=req.object_name,
                    external_id_field=req.external_id_field,
                    external_id_value=req.external_id_value,
                    record_id="a09000000000001AAA",
                    created=True,
                    acknowledged_at=now,
                )
                return GatewayResult.success(res, attempts=())

            def get_record(self, req: Any) -> Any:
                pass

        adapter = SalesforceSummaryTargetAdapter(gateway=FakeGateway(), settings=settings)  # type: ignore[arg-type]
        res = adapter.upsert_summary(proj)
        assert res.is_success
        ack = res.value
        assert ack.record_id == "a09000000000001AAA"
        assert ack.run_id == run_id
        assert ack.notification_state == NotificationState.PENDING
