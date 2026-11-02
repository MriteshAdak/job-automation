"""Salesforce Run Summary Notification Target, Deduplication Guard, and Dispatch Ledger (SF-09).

Implements:
- Compact Run_Summary__c schema model, fields, and validation boundaries.
- Single completion entitlement and immutable first-completion snapshot freezing.
- Monotonic revision sequencing and payload hash conflict protection.
- Fail-closed candidate recipient resolution via JA_Notification_Config__c.
- Guarded serialized dispatch claim and pre-send fence preventing duplicate deliveries across retries.
- Fixed bilingual notification templates (DE / EN) with secret and diagnostic sanitization.
- Handling of all four outcome categories: nonempty success, empty success, partial, failed.
- Operational recovery, ambiguous response reconciliation, and historical import suppression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
import threading
from typing import Any, Callable
import uuid
from zoneinfo import ZoneInfo

BERLIN_TZ = ZoneInfo("Europe/Berlin")

SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"(client_secret[=:\s]+)[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE),
    re.compile(r"(password[=:\s]+)[^\s,;]+", re.IGNORECASE),
    re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}:)[A-Za-z0-9_\-]{20,}"),
]

PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\[\w\s\-\.\\]+"),
    re.compile(r"/(?:Users|home|var|tmp|private|opt)/[\w\s\-\./]+"),
]


def sanitize_summary_text(text: str | None) -> str | None:
    """Scrub sensitive credentials, OAuth tokens, and local filesystem paths."""
    if not text:
        return text
    sanitized = text
    for pat in SECRET_PATTERNS:
        sanitized = pat.sub(r"\1[REDACTED_SECRET]", sanitized)
    for pat in PATH_PATTERNS:
        sanitized = pat.sub("[REDACTED_PATH]", sanitized)
    return sanitized


class PipelineStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class CoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class RunSummaryNotificationStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    DISPATCHING = "dispatching"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    SUPPRESSED = "suppressed"
    RETRY_WAIT = "retry_wait"


class LanguageCode(str, Enum):
    EN = "en"
    DE = "de"


class RunSummaryError(Exception):
    """Base error for SF-09 Run Summary operations."""
    pass


class RunSummaryValidationError(RunSummaryError):
    """Raised when incoming summary fields violate format or value rules."""
    pass


class RunSummaryRevisionConflictError(RunSummaryError):
    """Raised when an upsert has identical revision but differing payload hash."""
    pass


class RunSummaryStaleRevisionError(RunSummaryError):
    """Raised when an incoming revision is lower than an already applied revision."""
    pass


@dataclass
class RunSummaryNotificationConfig:
    """Configuration corresponding to singleton JA_Notification_Config__c."""
    org_key: str = "default"
    is_enabled: bool = False
    candidate_user_id: str | None = None
    preferred_language: LanguageCode = LanguageCode.EN
    enable_mobile: bool = False
    max_retry_attempts: int = 3
    initial_retry_delay_minutes: int = 1
    activation_watermark: datetime | None = None


@dataclass
class RunSummaryRecord:
    """In-memory representation of Salesforce Run_Summary__c custom object."""
    id: str
    run_id: uuid.UUID
    headline: str
    pipeline_status: PipelineStatus
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    contract_schema_version: str = "1.0"
    mapping_version: str = "1.1"
    summary_text: str = ""
    source_postings_count: int = 0
    canonical_jobs_new: int = 0
    canonical_jobs_updated: int = 0
    canonical_jobs_duplicate: int = 0
    eligible_count: int = 0
    review_count: int = 0
    rejected_count: int = 0
    sync_succeeded: int = 0
    sync_failed: int = 0
    quarantined_count: int = 0
    sources_attempted: list[str] = field(default_factory=list)
    sources_succeeded: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    stage_counts: dict[str, Any] = field(default_factory=dict)
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE
    projection_truncated: bool = False
    error_summary: str | None = None
    pending_work_summary: str | None = None
    revision: int = 1
    payload_hash: str = ""
    # Immutable First-Completion Entitlement
    first_completion_key: str = ""
    first_payload_hash: str = ""
    first_completed_at: datetime | None = None
    first_status: PipelineStatus | None = None
    first_headline: str = ""
    first_summary_text: str = ""
    completion_recorded_at: datetime | None = None
    # Server-managed Notification Lifecycle
    notification_recipient: str | None = None
    notification_status: RunSummaryNotificationStatus = RunSummaryNotificationStatus.NONE
    notification_claim_id: str | None = None
    notification_attempt_count: int = 0
    notification_last_attempt_at: datetime | None = None
    notification_next_attempt_at: datetime | None = None
    notification_receipt_id: str | None = None
    notification_accepted_at: datetime | None = None
    notification_error_code: str | None = None
    is_first_completion: bool = False


class RunSummaryAdmissionService:
    """Evaluates incoming run summaries, maintains monotonic revisions, and freezes completion snapshots."""

    def __init__(self, org_id: str = "00D000000000001EAA"):
        self.org_id = org_id[:15]

    def admit_summary(
        self,
        fields: dict[str, Any],
        existing: RunSummaryRecord | None = None,
        config: RunSummaryNotificationConfig | None = None,
    ) -> RunSummaryRecord:
        """Admit a summary payload, returning the updated or persisted RunSummaryRecord."""
        raw_run_id = fields.get("Run_Id__c")
        if not raw_run_id:
            raise RunSummaryValidationError("Run_Id__c is required.")
        try:
            run_uuid = uuid.UUID(str(raw_run_id).lower().strip())
        except (ValueError, TypeError) as e:
            raise RunSummaryValidationError(f"Invalid Run_Id__c UUID: {raw_run_id}") from e

        raw_status = str(fields.get("Pipeline_Status__c", "")).lower()
        if raw_status not in ("success", "partial", "failed"):
            raise RunSummaryValidationError(f"Invalid Pipeline_Status__c: {raw_status}")
        pipeline_status = PipelineStatus(raw_status)

        start_time = fields.get("Start_Time__c")
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        elif not isinstance(start_time, datetime):
            start_time = datetime.now(timezone.utc)

        end_time = fields.get("End_Time__c")
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        elif not isinstance(end_time, datetime):
            end_time = datetime.now(timezone.utc)

        if end_time < start_time:
            raise RunSummaryValidationError("End_Time__c cannot precede Start_Time__c.")

        duration = float(fields.get("Duration_Seconds__c", (end_time - start_time).total_seconds()))
        if duration < 0:
            raise RunSummaryValidationError("Duration_Seconds__c cannot be negative.")

        headline = sanitize_summary_text(str(fields.get("Headline__c", fields.get("Name", "Run Summary"))))[:255]
        summary_text = sanitize_summary_text(str(fields.get("Summary_Text__c", "")))[:2000]
        error_summary = sanitize_summary_text(fields.get("Error_Summary__c"))
        if error_summary:
            error_summary = error_summary[:500]
        pending_work = sanitize_summary_text(fields.get("Pending_Work_Summary__c"))
        if pending_work:
            pending_work = pending_work[:500]

        new_revision = int(fields.get("Revision__c", 1))
        payload_hash = str(fields.get("Payload_Hash__c", ""))
        first_payload_hash = str(fields.get("First_Payload_Hash__c", payload_hash))

        sources_attempted = fields.get("Sources_Attempted__c", [])
        if isinstance(sources_attempted, str):
            sources_attempted = [s.strip() for s in sources_attempted.split(",") if s.strip()]

        sources_succeeded = fields.get("Sources_Succeeded__c", [])
        if isinstance(sources_succeeded, str):
            sources_succeeded = [s.strip() for s in sources_succeeded.split(",") if s.strip()]

        sources_failed = fields.get("Sources_Failed__c", [])
        if isinstance(sources_failed, str):
            sources_failed = [s.strip() for s in sources_failed.split(",") if s.strip()]

        coverage_status_str = str(fields.get("Coverage_Status__c", "complete")).lower()
        coverage_status = CoverageStatus(coverage_status_str) if coverage_status_str in ("complete", "partial", "unavailable") else CoverageStatus.COMPLETE

        is_first_hint = bool(fields.get("Is_First_Completion__c", False) or fields.get("Notification_Status__c") == "pending")

        expected_key = f"{self.org_id}:{run_uuid}"

        if existing is not None:
            # Update path: revision checks
            if new_revision < existing.revision:
                raise RunSummaryStaleRevisionError(
                    f"Stale revision rejected: received {new_revision} < existing {existing.revision}"
                )

            if new_revision == existing.revision:
                if existing.payload_hash and payload_hash and existing.payload_hash != payload_hash:
                    raise RunSummaryRevisionConflictError(
                        f"Revision conflict: same revision {new_revision} with differing payload hash."
                    )
                # Replay of identical revision: return existing without modifying markers
                return existing

            # Higher revision (resumed run):
            # Update latest-result fields, but preserve FIRST-completion snapshots and markers
            existing.revision = new_revision
            existing.payload_hash = payload_hash
            existing.pipeline_status = pipeline_status
            existing.start_time = start_time
            existing.end_time = end_time
            existing.duration_seconds = duration
            existing.headline = headline
            existing.summary_text = summary_text
            existing.error_summary = error_summary
            existing.pending_work_summary = pending_work
            existing.source_postings_count = int(fields.get("Source_Postings_Count__c", existing.source_postings_count))
            existing.canonical_jobs_new = int(fields.get("Canonical_Jobs_New__c", existing.canonical_jobs_new))
            existing.canonical_jobs_updated = int(fields.get("Canonical_Jobs_Updated__c", existing.canonical_jobs_updated))
            existing.canonical_jobs_duplicate = int(fields.get("Canonical_Jobs_Duplicate__c", existing.canonical_jobs_duplicate))
            existing.eligible_count = int(fields.get("Eligible_Count__c", existing.eligible_count))
            existing.review_count = int(fields.get("Review_Count__c", existing.review_count))
            existing.rejected_count = int(fields.get("Rejected_Count__c", existing.rejected_count))
            existing.sources_attempted = sources_attempted
            existing.sources_succeeded = sources_succeeded
            existing.sources_failed = sources_failed
            existing.coverage_status = coverage_status
            # Invariant: First completion and notification state remain FROZEN
            return existing

        # Insert path: first terminal completion admission
        rec_id = f"a0{uuid.uuid4().hex[:15]}"
        now = datetime.now(timezone.utc)

        first_key = str(fields.get("First_Completion_Key__c", expected_key))
        if first_key != expected_key:
            # Normalize to canonical org format
            first_key = expected_key

        first_sum_text = summary_text or error_summary or ""

        rec = RunSummaryRecord(
            id=rec_id,
            run_id=run_uuid,
            headline=headline,
            pipeline_status=pipeline_status,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            contract_schema_version=str(fields.get("Contract_Schema_Version__c", "1.0")),
            mapping_version=str(fields.get("Mapping_Version__c", "1.1")),
            summary_text=summary_text,
            source_postings_count=int(fields.get("Source_Postings_Count__c", 0)),
            canonical_jobs_new=int(fields.get("Canonical_Jobs_New__c", 0)),
            canonical_jobs_updated=int(fields.get("Canonical_Jobs_Updated__c", 0)),
            canonical_jobs_duplicate=int(fields.get("Canonical_Jobs_Duplicate__c", 0)),
            eligible_count=int(fields.get("Eligible_Count__c", 0)),
            review_count=int(fields.get("Review_Count__c", 0)),
            rejected_count=int(fields.get("Rejected_Count__c", 0)),
            sync_succeeded=int(fields.get("Sync_Succeeded__c", 0)),
            sync_failed=int(fields.get("Sync_Failed__c", 0)),
            quarantined_count=int(fields.get("Quarantined_Count__c", 0)),
            sources_attempted=sources_attempted,
            sources_succeeded=sources_succeeded,
            sources_failed=sources_failed,
            coverage_status=coverage_status,
            projection_truncated=bool(fields.get("Projection_Truncated__c", False)),
            error_summary=error_summary,
            pending_work_summary=pending_work,
            revision=new_revision,
            payload_hash=payload_hash,
            first_completion_key=first_key,
            first_payload_hash=first_payload_hash or payload_hash,
            first_completed_at=end_time,
            first_status=pipeline_status,
            first_headline=headline,
            first_summary_text=first_sum_text,
            completion_recorded_at=now,
            is_first_completion=True,
        )

        # Evaluate notification eligibility
        if config is not None and config.is_enabled and config.candidate_user_id:
            # Check watermark for historical suppression
            if config.activation_watermark and end_time < config.activation_watermark:
                rec.notification_status = RunSummaryNotificationStatus.SUPPRESSED
                rec.notification_error_code = "HISTORICAL_PRIOR_TO_WATERMARK"
                rec.notification_recipient = config.candidate_user_id
            else:
                rec.notification_status = RunSummaryNotificationStatus.PENDING
                rec.notification_recipient = config.candidate_user_id
        else:
            rec.notification_status = RunSummaryNotificationStatus.NONE

        return rec


class RunSummaryDispatchService:
    """Dispatches run summary completion notifications with mutual exclusion, pre-send fence, and state tracking."""

    def __init__(self, lock: threading.Lock | None = None):
        self._lock = lock or threading.Lock()

    def dispatch(
        self,
        record: RunSummaryRecord,
        config: RunSummaryNotificationConfig,
        notif_sender: Callable[[str, str, str, str], bool] | None = None,
    ) -> RunSummaryRecord:
        """Execute guarded pre-send fence and notification dispatch."""
        with self._lock:
            if record.notification_status not in (
                RunSummaryNotificationStatus.PENDING,
                RunSummaryNotificationStatus.RETRY_WAIT,
            ):
                return record

            now = datetime.now(timezone.utc)
            if record.notification_status == RunSummaryNotificationStatus.RETRY_WAIT:
                if record.notification_next_attempt_at and record.notification_next_attempt_at > now:
                    return record

            if not record.notification_recipient:
                record.notification_status = RunSummaryNotificationStatus.FAILED
                record.notification_error_code = "MISSING_RECIPIENT"
                return record

            if not config.is_enabled:
                record.notification_status = RunSummaryNotificationStatus.SUPPRESSED
                record.notification_error_code = "CONFIG_DISABLED"
                return record

            # Pre-send fence: unique attempt claim
            claim_id = hashlib.sha256(f"{uuid.uuid4()}:{record.id}:{now.isoformat()}".encode()).hexdigest()[:32]
            record.notification_claim_id = claim_id
            record.notification_status = RunSummaryNotificationStatus.DISPATCHING
            record.notification_attempt_count += 1
            record.notification_last_attempt_at = now

            # Format localized notification
            title, body = format_run_summary_notification(record, language=config.preferred_language.value)

            try:
                # Deliver notification via custom notification boundary
                success = True
                if notif_sender is not None:
                    success = notif_sender(title, body, record.id, record.notification_recipient)

                if success:
                    record.notification_status = RunSummaryNotificationStatus.CONFIRMED
                    record.notification_accepted_at = datetime.now(timezone.utc)
                    record.notification_receipt_id = claim_id
                    record.notification_error_code = None
                else:
                    record.notification_status = RunSummaryNotificationStatus.FAILED
                    record.notification_error_code = "SEND_RETURNED_FALSE"
            except TimeoutError:
                # Ambiguous network timeout: fence in UNKNOWN
                record.notification_status = RunSummaryNotificationStatus.UNKNOWN
                record.notification_error_code = "AMBIGUOUS_SEND"
            except Exception as e:
                err_str = str(e).lower()
                if "timeout" in err_str or "unconfirmed" in err_str or "network" in err_str:
                    record.notification_status = RunSummaryNotificationStatus.UNKNOWN
                    record.notification_error_code = "AMBIGUOUS_SEND"
                else:
                    max_att = config.max_retry_attempts
                    if record.notification_attempt_count < max_att:
                        record.notification_status = RunSummaryNotificationStatus.RETRY_WAIT
                        delay_mins = config.initial_retry_delay_minutes * (2 ** (record.notification_attempt_count - 1))
                        record.notification_next_attempt_at = now + timedelta(minutes=delay_mins)
                        record.notification_error_code = "PRE_SEND_FAILURE"
                    else:
                        record.notification_status = RunSummaryNotificationStatus.FAILED
                        record.notification_error_code = "MAX_RETRIES_EXCEEDED"

            return record


class RunSummaryRecoveryService:
    """Operational retry, reconciliation, and suppression manager."""

    @staticmethod
    def retry_failed(record: RunSummaryRecord) -> RunSummaryRecord:
        """Schedule a failed pre-send notification for retry under the same completion key."""
        if record.notification_status == RunSummaryNotificationStatus.FAILED:
            record.notification_status = RunSummaryNotificationStatus.RETRY_WAIT
            record.notification_next_attempt_at = datetime.now(timezone.utc)
            record.notification_error_code = "OPERATOR_RETRY_SCHEDULED"
        return record

    @staticmethod
    def reconcile_unknown(
        record: RunSummaryRecord,
        was_delivered: bool,
        receipt_id: str | None = None,
    ) -> RunSummaryRecord:
        """Reconcile an ambiguous unknown notification state based on operator verification."""
        if record.notification_status != RunSummaryNotificationStatus.UNKNOWN:
            return record

        if was_delivered:
            record.notification_status = RunSummaryNotificationStatus.CONFIRMED
            record.notification_accepted_at = datetime.now(timezone.utc)
            record.notification_receipt_id = receipt_id or "MANUAL_RECONCILED"
            record.notification_error_code = None
        else:
            # Proven non-send: return to retry_wait for safe re-dispatch under same key
            record.notification_status = RunSummaryNotificationStatus.RETRY_WAIT
            record.notification_next_attempt_at = datetime.now(timezone.utc)
            record.notification_error_code = "RECONCILED_NON_SEND"
        return record

    @staticmethod
    def suppress_historical(
        records: list[RunSummaryRecord],
        watermark: datetime,
    ) -> int:
        """Mark un-notified records completed prior to watermark as suppressed."""
        count = 0
        for r in records:
            if (
                r.first_completed_at
                and r.first_completed_at < watermark
                and r.notification_status in (RunSummaryNotificationStatus.NONE, RunSummaryNotificationStatus.PENDING)
            ):
                r.notification_status = RunSummaryNotificationStatus.SUPPRESSED
                r.notification_error_code = "HISTORICAL_PRIOR_TO_WATERMARK"
                count += 1
        return count


def format_run_summary_notification(
    record: RunSummaryRecord,
    language: str = "en",
) -> tuple[str, str]:
    """Build fixed, bounded notification title and body for bell notification."""
    status = record.first_status or record.pipeline_status
    obs = record.source_postings_count
    new_jobs = record.canonical_jobs_new
    updated_jobs = record.canonical_jobs_updated
    dup_obs = record.canonical_jobs_duplicate
    headline = record.first_headline or record.headline
    error_summary = record.first_summary_text or record.error_summary or "None"

    dt_str = ""
    if record.first_completed_at:
        dt_berlin = record.first_completed_at.astimezone(BERLIN_TZ)
        dt_str = dt_berlin.strftime("%Y-%m-%d %H:%M:%S %Z")

    if language == "de":
        if status == PipelineStatus.SUCCESS:
            if obs == 0 and record.coverage_status == CoverageStatus.COMPLETE:
                title = "Suchlauf abgeschlossen: Keine Ausschreibungen"
                body = f"Lauf {record.run_id}: Keine Ausschreibungen in konfigurierten Quellen gefunden.\nAbgeschlossen um {dt_str}."
            elif obs > 0 and new_jobs == 0:
                title = "Suchlauf abgeschlossen: Keine neuen Stellen"
                body = f"Lauf {record.run_id}: {headline}\nGefunden: {obs} Ausschreibungen (+0 neue, {updated_jobs} aktualisiert, {dup_obs} Duplikate).\nAbgeschlossen um {dt_str}."
            else:
                title = "Suchlauf abgeschlossen: Erfolgreich"
                body = f"Lauf {record.run_id}: {headline}\nGefunden: {obs} Ausschreibungen (+{new_jobs} neu, {updated_jobs} aktualisiert, {dup_obs} Duplikate).\nAbgeschlossen um {dt_str}."
        elif status == PipelineStatus.PARTIAL:
            title = "Suchlauf unvollständig: Teilweise"
            body = f"Lauf {record.run_id}: Suche mit unvollständiger Quellenabdeckung beendet.\nFehler: {error_summary}\nAbgeschlossen um {dt_str}."
        else:
            title = "Suchlauf fehlgeschlagen: Fehler"
            body = f"Lauf {record.run_id}: Suche vor dem Abschluss fehlgeschlagen.\nFehler: {error_summary}\nAbgeschlossen um {dt_str}."
    else:
        if status == PipelineStatus.SUCCESS:
            if obs == 0 and record.coverage_status == CoverageStatus.COMPLETE:
                title = "Run Completed: No postings found"
                body = f"Run {record.run_id}: No postings found across configured sources.\nCompleted at {dt_str}."
            elif obs > 0 and new_jobs == 0:
                title = "Run Completed: No new jobs"
                body = f"Run {record.run_id}: {headline}\nObserved: {obs} postings (+0 new, {updated_jobs} updated, {dup_obs} duplicate).\nCompleted at {dt_str}."
            else:
                title = "Run Completed: Success"
                body = f"Run {record.run_id}: {headline}\nObserved: {obs} postings (+{new_jobs} new, {updated_jobs} updated, {dup_obs} duplicate).\nCompleted at {dt_str}."
        elif status == PipelineStatus.PARTIAL:
            title = "Run Completed: Partial"
            body = f"Run {record.run_id}: Search partial with incomplete source coverage.\nSafe error digest: {error_summary}\nCompleted at {dt_str}."
        else:
            title = "Run Completed: Failed"
            body = f"Run {record.run_id}: Search failed before completion.\nSafe error digest: {error_summary}\nCompleted at {dt_str}."

    # Enforce strict character limits: Title <= 250, Body <= 750
    return title[:250], body[:750]
