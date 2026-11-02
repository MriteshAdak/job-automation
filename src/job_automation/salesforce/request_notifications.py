"""Salesforce Generation Request Notifications, Flows, and Durable Delivery Ledger (SF-08).

Implements:
- SF08RequestNotificationEventV1 contract and canonical event keys.
- Unique AlertKey generation and deterministic conflict detection.
- Notification admission with format completeness and candidate file access verification.
- Fixed bilingual notification templates (DE / EN) with strict diagnostic sanitization.
- Durable lifecycle: Pending, Blocked, Dispatching, Accepted, Retry_Wait, Uncertain, Suppressed, Dead_Letter.
- Serialized dispatch claim and pre-send fence preventing duplicate deliveries across retries and restarts.
- Admin singleton configuration (JA_Notification_Config__c) and fail-closed security.
- Recovery, bounded backoff, and backlog inspection.
- Invariant: Draft delivery never implies document approval.
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

from job_automation.generation.delivery_records import (
    DeliverySetReceipt,
    RemoteArtifactMapping,
    ReviewProjection,
)
from job_automation.generation.request_mapping import canonicalize_salesforce_id
from job_automation.salesforce.artifact_review import (
    ArtifactReviewService,
    ApprovalStatus,
    FormatReviewCard,
)
from job_automation.salesforce.generation_submission import (
    GenerationSubmissionService,
    SimulatedGenerationRequest,
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")


class NotificationKind(str, Enum):
    """Event kind admitted to notification ledger."""
    READY = "ready"
    ACTION_REQUIRED = "action_required"


class NotificationStatus(str, Enum):
    """Durable lifecycle states of JA_Request_Notification__c."""
    PENDING = "Pending"
    BLOCKED = "Blocked"
    DISPATCHING = "Dispatching"
    ACCEPTED = "Accepted"
    RETRY_WAIT = "Retry_Wait"
    UNCERTAIN = "Uncertain"
    SUPPRESSED = "Suppressed"
    DEAD_LETTER = "Dead_Letter"


class NotificationChannel(str, Enum):
    """Supported notification delivery channels."""
    SALESFORCE_CUSTOM_NOTIFICATION = "salesforce_custom_notification"


class LanguageCode(str, Enum):
    """Notification template language."""
    EN = "en"
    DE = "de"


class AdmissionOutcome(str, Enum):
    """Outcome of attempting to admit an event into the notification ledger."""
    ADMITTED = "admitted"
    REPLAYED = "replayed"
    BLOCKED = "blocked"
    SUPPRESSED = "suppressed"
    CONFLICT = "conflict"
    NOT_ELIGIBLE = "not_eligible"


@dataclass
class NotificationConfig:
    """Admin configuration record matching JA_Notification_Config__c."""
    org_key: str = "default"
    is_enabled: bool = False
    candidate_user_id: str | None = None
    permitted_event_kinds: tuple[str, ...] = ("ready", "action_required")
    preferred_language: LanguageCode = LanguageCode.EN
    enable_mobile: bool = False
    max_retry_attempts: int = 3
    initial_retry_delay_minutes: int = 1
    activation_watermark: datetime | None = None


@dataclass(frozen=True)
class FormatBinding:
    """Verified exact binding for a specific format."""
    format: str
    artifact_id: str
    artifact_version: int
    content_hash: str
    content_document_id: str
    content_version_id: str


@dataclass(frozen=True)
class RecipientAccessEvidence:
    """Verification evidence that candidate user possesses read access."""
    recipient_user_id: str
    verified_at: datetime
    share_type: str
    visibility: str
    is_accessible: bool


@dataclass(frozen=True)
class RequestNotificationEventV1:
    """Additive integration envelope SF08RequestNotificationEventV1."""
    schema_version: str = "1.0"
    org_id: str = "00D000000000001AAA"
    request_id: str = ""
    salesforce_request_id: str = ""
    event_kind: NotificationKind = NotificationKind.READY
    source_event_key: str = ""
    occurrence_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_revision: int = 1
    payload_fingerprint: str = ""
    # Ready specific
    artifact_set_id: str | None = None
    artifact_set_version: int | None = None
    required_formats: tuple[str, ...] = ("docx", "pdf")
    bindings: tuple[FormatBinding, ...] = ()
    access_evidence: RecipientAccessEvidence | None = None
    # Action required specific
    failure_episode_id: str | None = None
    action_code: str | None = None
    safe_reason: str | None = None


@dataclass
class RequestNotificationRecord:
    """Durable alert ledger record matching JA_Request_Notification__c."""
    id: str
    alert_key: str
    source_event_key: str
    event_kind: NotificationKind
    generation_request_id: str
    recipient_user_id: str
    channel: NotificationChannel = NotificationChannel.SALESFORCE_CUSTOM_NOTIFICATION
    status: NotificationStatus = NotificationStatus.PENDING
    payload_fingerprint: str = ""
    source_revision: int = 1
    artifact_set_id: str | None = None
    artifact_set_version: int | None = None
    failure_episode_id: str | None = None
    action_code: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    next_retry_at: datetime | None = None
    attempt_identifier: str | None = None
    dispatched_at: datetime | None = None
    accepted_at: datetime | None = None
    safe_error_code: str | None = None
    uncertainty_reason: str | None = None
    target_record_id: str = ""
    notification_title: str = ""
    notification_body: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class AdmissionResult:
    """Result of admission evaluation."""
    outcome: AdmissionOutcome
    alert_key: str | None = None
    notification_id: str | None = None
    reason_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class DispatchResult:
    """Result of dispatch execution."""
    notification_id: str
    alert_key: str
    status: NotificationStatus
    attempt: int
    safe_error_code: str | None = None
    uncertainty_reason: str | None = None


# --- Key and Digest Generators ---

def compute_ready_event_key(
    org_id: str,
    request_id: str,
    set_id: str,
    set_version: int,
    bindings: list[FormatBinding] | tuple[FormatBinding, ...],
) -> str:
    """Compute deterministic canonical readiness key over immutable version bindings."""
    sorted_bindings = sorted(bindings, key=lambda b: b.format.lower())
    canonical_repr = [
        {
            "format": b.format.lower(),
            "artifact_id": b.artifact_id,
            "artifact_version": b.artifact_version,
            "content_hash": b.content_hash,
            "content_version_id": b.content_version_id,
        }
        for b in sorted_bindings
    ]
    set_hash = hashlib.sha256(
        json.dumps(canonical_repr, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"ready:{canonicalize_salesforce_id(org_id)}:{request_id}:{set_id}:{set_version}:{set_hash}"


def compute_failure_event_key(
    org_id: str,
    request_id: str,
    episode_id: str,
) -> str:
    """Compute deterministic canonical failure episode key."""
    return f"failure:{canonicalize_salesforce_id(org_id)}:{request_id}:{episode_id}"


def compute_alert_key(
    source_event_key: str,
    recipient_user_id: str,
    channel: str = NotificationChannel.SALESFORCE_CUSTOM_NOTIFICATION.value,
) -> str:
    """Compute deterministic unique AlertKey (SHA-256 of canonical tuple)."""
    canonical_tuple = f"{source_event_key}:{canonicalize_salesforce_id(recipient_user_id)}:{channel}"
    return hashlib.sha256(canonical_tuple.encode("utf-8")).hexdigest()


def compute_payload_fingerprint(payload_dict: dict[str, Any]) -> str:
    """Compute SHA-256 hex digest of sorted canonical payload JSON."""
    return hashlib.sha256(
        json.dumps(payload_dict, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


# --- Safe Bilingual Template Formatter ---

TEMPLATES = {
    NotificationKind.READY: {
        LanguageCode.EN: {
            "title": "Draft ready for review",
            "body": "Request {requestNumber}: DOCX and PDF drafts are available. Open the request to review them.",
        },
        LanguageCode.DE: {
            "title": "Entwurf bereit zur Prüfung",
            "body": "Anfrage {requestNumber}: DOCX- und PDF-Entwürfe stehen zur Verfügung. Öffnen Sie die Anfrage zur Prüfung.",
        },
    },
    NotificationKind.ACTION_REQUIRED: {
        "terminal_failure": {
            LanguageCode.EN: {
                "title": "Draft request needs attention",
                "body": "Request {requestNumber} could not complete. Open the request for the next step.",
            },
            LanguageCode.DE: {
                "title": "Entwurfsanfrage erfordert Aufmerksamkeit",
                "body": "Anfrage {requestNumber} konnte nicht abgeschlossen werden. Öffnen Sie die Anfrage für den nächsten Schritt.",
            },
        },
        "upload_intervention_required": {
            LanguageCode.EN: {
                "title": "Draft delivery needs attention",
                "body": "Request {requestNumber}: file delivery is blocked. Open the request for the next step.",
            },
            LanguageCode.DE: {
                "title": "Entwurfslieferung erfordert Aufmerksamkeit",
                "body": "Anfrage {requestNumber}: Dateiauslieferung ist blockiert. Öffnen Sie die Anfrage für den nächsten Schritt.",
            },
        },
    },
}

ALLOWLISTED_ACTION_CODES = {
    "terminal_failure",
    "upload_intervention_required",
    "job_unavailable",
    "capacity_exceeded",
    "permission_denied",
    "rate_limited",
}


def sanitize_diagnostic_text(text: str | None) -> str:
    """Strip tokens, paths, prompt excerpts, URLs, and HTML from diagnostic text."""
    if not text:
        return ""
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", "", text)
    # Strip URLs
    cleaned = re.sub(r"https?://\S+", "[URL_REDACTED]", cleaned)
    # Strip file paths
    cleaned = re.sub(r"[A-Za-z]:\\[\w\s\\.-]+", "[PATH_REDACTED]", cleaned)
    cleaned = re.sub(r"/[\w\s/.-]+", "[PATH_REDACTED]", cleaned)
    # Strip token patterns (alphanumeric >= 24 chars)
    cleaned = re.sub(r"\b[A-Za-z0-9_-]{24,}\b", "[TOKEN_REDACTED]", cleaned)
    return cleaned.strip()


def format_notification_content(
    kind: NotificationKind,
    action_code: str | None,
    request_number: str,
    language: LanguageCode = LanguageCode.EN,
) -> tuple[str, str]:
    """Format safe title and body according to reviewed bilingual templates."""
    lang = LanguageCode.DE if language == LanguageCode.DE else LanguageCode.EN
    safe_number = sanitize_diagnostic_text(request_number)

    if kind == NotificationKind.READY:
        tmpl = TEMPLATES[NotificationKind.READY][lang]
        return tmpl["title"], tmpl["body"].format(requestNumber=safe_number)

    # Action required
    sub_key = "upload_intervention_required" if action_code == "upload_intervention_required" else "terminal_failure"
    tmpl = TEMPLATES[NotificationKind.ACTION_REQUIRED][sub_key][lang]
    return tmpl["title"], tmpl["body"].format(requestNumber=safe_number)


# --- Request Notification Service ---

class RequestNotificationService:
    """Comprehensive service implementing SF-08 notification contracts and lifecycle."""

    def __init__(
        self,
        submission_service: GenerationSubmissionService | None = None,
        review_service: ArtifactReviewService | None = None,
        org_id: str = "00D000000000001AAA",
        config: NotificationConfig | None = None,
        sender_callback: Callable[[RequestNotificationRecord], bool] | None = None,
    ) -> None:
        self.org_id = org_id
        self.submission_service = submission_service or GenerationSubmissionService()
        self.review_service = review_service or ArtifactReviewService(
            submission_service=self.submission_service, org_id=org_id
        )
        self.config = config or NotificationConfig(org_key="default", is_enabled=False)
        self.sender_callback = sender_callback
        self._lock = threading.RLock()

        # Alert ledger: id -> RequestNotificationRecord
        self.notifications: dict[str, RequestNotificationRecord] = {}
        # External ID lookup: alert_key -> id
        self.alert_keys: dict[str, str] = {}
        self._next_notification_number = 1

        # Failure episodes: (org_id, request_id) -> episode_id
        self._active_failure_episodes: dict[tuple[str, str], str] = {}

    def configure(
        self,
        is_enabled: bool,
        candidate_user_id: str | None,
        language: LanguageCode = LanguageCode.EN,
        enable_mobile: bool = False,
        activation_watermark: datetime | None = None,
        max_retries: int = 3,
        initial_retry_delay_minutes: int = 1,
    ) -> NotificationConfig:
        """Update singleton notification configuration."""
        with self._lock:
            self.config = NotificationConfig(
                org_key="default",
                is_enabled=is_enabled,
                candidate_user_id=candidate_user_id,
                permitted_event_kinds=("ready", "action_required"),
                preferred_language=language,
                enable_mobile=enable_mobile,
                max_retry_attempts=max_retries,
                initial_retry_delay_minutes=initial_retry_delay_minutes,
                activation_watermark=activation_watermark,
            )
            return self.config

    def get_notification(self, notification_id: str) -> RequestNotificationRecord | None:
        """Fetch notification ledger record by ID."""
        with self._lock:
            return self.notifications.get(notification_id)

    def get_notification_by_alert_key(self, alert_key: str) -> RequestNotificationRecord | None:
        """Fetch notification ledger record by unique alert key."""
        with self._lock:
            nid = self.alert_keys.get(alert_key)
            return self.notifications.get(nid) if nid else None

    # --- Admission Logic (S03) ---

    def admit_transition(
        self,
        request_id: str,
        failure_episode_id: str | None = None,
        action_code: str | None = None,
        is_upload_intervention: bool = False,
    ) -> AdmissionResult:
        """Evaluate request transition and admit durable notification record."""
        with self._lock:
            req = self.submission_service.get_request(request_id)
            if not req:
                return AdmissionResult(
                    outcome=AdmissionOutcome.NOT_ELIGIBLE,
                    reason_code="REQUEST_NOT_FOUND",
                    message="Target Generation_Request__c not found",
                )

            current_status = req.status
            canon_req_id = canonicalize_salesforce_id(req.id)

            # Invariant: Pending / Running -> zero ready or failure alert
            if current_status in ("Pending", "Running"):
                return AdmissionResult(
                    outcome=AdmissionOutcome.NOT_ELIGIBLE,
                    reason_code="INTERMEDIATE_PROCESSING_STATE",
                    message=f"Request is in intermediate state {current_status}; no alert eligible.",
                )

            # Invariant: Upload_Pending without explicit intervention -> zero alert
            if current_status == "Upload_Pending" and not is_upload_intervention:
                return AdmissionResult(
                    outcome=AdmissionOutcome.NOT_ELIGIBLE,
                    reason_code="UPLOAD_PENDING_NORMAL",
                    message="Upload_Pending is awaiting file delivery; no ready alert permitted.",
                )

            # Determine kind
            if current_status == "Ready_for_Review":
                kind = NotificationKind.READY
            elif current_status == "Failed" or (current_status == "Upload_Pending" and is_upload_intervention):
                kind = NotificationKind.ACTION_REQUIRED
            else:
                return AdmissionResult(
                    outcome=AdmissionOutcome.NOT_ELIGIBLE,
                    reason_code="UNKNOWN_STATUS",
                    message=f"Status {current_status} is not eligible for notification.",
                )

            # Check config: must be enabled with candidate user
            if not self.config.is_enabled or not self.config.candidate_user_id:
                safe_code = "CONFIG_DISABLED" if not self.config.is_enabled else "RECIPIENT_NOT_CONFIGURED"
                return AdmissionResult(
                    outcome=AdmissionOutcome.BLOCKED,
                    reason_code=safe_code,
                    message="Notifications disabled or recipient user not configured.",
                )

            candidate_user_id = self.config.candidate_user_id

            # Evaluate Ready Eligibility
            if kind == NotificationKind.READY:
                # 1. Authoritative complete set check: must have BOTH docx and pdf registered
                ui_state = self.review_service.get_review_ui_state(
                    req.id, candidate_user_id=candidate_user_id
                )
                docx_card = ui_state.cards.get("docx")
                pdf_card = ui_state.cards.get("pdf")
                if not docx_card or not pdf_card or not docx_card.review_id or not pdf_card.review_id:
                    return AdmissionResult(
                        outcome=AdmissionOutcome.BLOCKED,
                        reason_code="INCOMPLETE_FORMATS",
                        message="Delivered artifact set is incomplete (requires both DOCX and PDF).",
                    )

                # Fetch binding details
                r_docx = self.review_service._review_records[docx_card.review_id]
                r_pdf = self.review_service._review_records[pdf_card.review_id]

                bindings = [
                    FormatBinding(
                        format="docx",
                        artifact_id=r_docx.artifact_id,
                        artifact_version=r_docx.artifact_version,
                        content_hash=r_docx.content_hash,
                        content_document_id=r_docx.content_document_id,
                        content_version_id=r_docx.content_version_id,
                    ),
                    FormatBinding(
                        format="pdf",
                        artifact_id=r_pdf.artifact_id,
                        artifact_version=r_pdf.artifact_version,
                        content_hash=r_pdf.content_hash,
                        content_document_id=r_pdf.content_document_id,
                        content_version_id=r_pdf.content_version_id,
                    ),
                ]

                set_id = r_docx.artifact_set_id
                set_ver = r_docx.artifact_version
                source_event_key = compute_ready_event_key(
                    self.org_id, canon_req_id, set_id, set_ver, bindings
                )
                payload_dict = {
                    "kind": kind.value,
                    "set_id": set_id,
                    "set_version": set_ver,
                    "docx_hash": r_docx.content_hash,
                    "pdf_hash": r_pdf.content_hash,
                    "docx_cv": r_docx.content_version_id,
                    "pdf_cv": r_pdf.content_version_id,
                }
                action_code_val = None
                payload_fingerprint = compute_payload_fingerprint(payload_dict)
                alert_key = compute_alert_key(source_event_key, candidate_user_id)

                # 2. Recipient file accessibility verification
                if not docx_card.is_accessible or not pdf_card.is_accessible:
                    if alert_key not in self.alert_keys:
                        nid = f"a05{self._next_notification_number:012d}AAA"
                        self._next_notification_number += 1
                        request_num = req.name or f"GR-{canon_req_id[-6:]}"
                        b_title, b_body = format_notification_content(
                            kind, None, request_num, self.config.preferred_language
                        )
                        blocked_record = RequestNotificationRecord(
                            id=nid,
                            alert_key=alert_key,
                            source_event_key=source_event_key,
                            event_kind=kind,
                            generation_request_id=canon_req_id,
                            recipient_user_id=candidate_user_id,
                            channel=NotificationChannel.SALESFORCE_CUSTOM_NOTIFICATION,
                            status=NotificationStatus.BLOCKED,
                            payload_fingerprint=payload_fingerprint,
                            source_revision=1,
                            artifact_set_id=set_id,
                            artifact_set_version=set_ver,
                            target_record_id=canon_req_id,
                            notification_title=b_title,
                            notification_body=b_body,
                            safe_error_code="RECIPIENT_ACCESS_DENIED",
                        )
                        self.notifications[nid] = blocked_record
                        self.alert_keys[alert_key] = nid
                        return AdmissionResult(
                            outcome=AdmissionOutcome.BLOCKED,
                            alert_key=alert_key,
                            notification_id=nid,
                            reason_code="RECIPIENT_ACCESS_DENIED",
                            message="Delivered files are not accessible to configured recipient.",
                        )
                    else:
                        nid = self.alert_keys[alert_key]
                        return AdmissionResult(
                            outcome=AdmissionOutcome.BLOCKED,
                            alert_key=alert_key,
                            notification_id=nid,
                            reason_code="RECIPIENT_ACCESS_DENIED",
                            message="Delivered files are not accessible to configured recipient.",
                        )

            else:
                # Action Required / Failure
                if not failure_episode_id:
                    # Look up active episode or create new deterministic episode
                    ep_key = (self.org_id, canon_req_id)
                    if ep_key in self._active_failure_episodes:
                        failure_episode_id = self._active_failure_episodes[ep_key]
                    else:
                        failure_episode_id = str(uuid.uuid4())
                        self._active_failure_episodes[ep_key] = failure_episode_id

                action_code_val = action_code or (
                    "upload_intervention_required" if is_upload_intervention else "terminal_failure"
                )
                source_event_key = compute_failure_event_key(
                    self.org_id, canon_req_id, failure_episode_id
                )
                payload_dict = {
                    "kind": kind.value,
                    "episode_id": failure_episode_id,
                    "action_code": action_code_val,
                }
                set_id = None
                set_ver = None

            payload_fingerprint = compute_payload_fingerprint(payload_dict)
            alert_key = compute_alert_key(source_event_key, candidate_user_id)

            # Check existing ledger record
            if alert_key in self.alert_keys:
                existing_nid = self.alert_keys[alert_key]
                existing_rec = self.notifications[existing_nid]

                # Conflict check: same key with different payload
                if existing_rec.payload_fingerprint != payload_fingerprint:
                    return AdmissionResult(
                        outcome=AdmissionOutcome.CONFLICT,
                        alert_key=alert_key,
                        notification_id=existing_nid,
                        reason_code="PAYLOAD_FINGERPRINT_CONFLICT",
                        message="AlertKey collision with conflicting immutable payload.",
                    )

                # Replay check
                if existing_rec.status == NotificationStatus.ACCEPTED:
                    return AdmissionResult(
                        outcome=AdmissionOutcome.REPLAYED,
                        alert_key=alert_key,
                        notification_id=existing_nid,
                        reason_code="ALREADY_ACCEPTED",
                        message="Alert has already been accepted and dispatched.",
                    )
                elif existing_rec.status in (NotificationStatus.PENDING, NotificationStatus.DISPATCHING, NotificationStatus.RETRY_WAIT):
                    return AdmissionResult(
                        outcome=AdmissionOutcome.REPLAYED,
                        alert_key=alert_key,
                        notification_id=existing_nid,
                        reason_code="IN_FLIGHT",
                        message="Alert is currently pending or in-flight.",
                    )
                elif existing_rec.status == NotificationStatus.BLOCKED:
                    # Access or config repaired -> release existing blocked alert to PENDING
                    existing_rec.status = NotificationStatus.PENDING
                    existing_rec.safe_error_code = None
                    existing_rec.updated_at = datetime.now(timezone.utc)
                    return AdmissionResult(
                        outcome=AdmissionOutcome.ADMITTED,
                        alert_key=alert_key,
                        notification_id=existing_nid,
                        reason_code="BLOCKED_RELEASED",
                        message="Previously blocked alert released to pending.",
                    )
                else:
                    return AdmissionResult(
                        outcome=AdmissionOutcome.REPLAYED,
                        alert_key=alert_key,
                        notification_id=existing_nid,
                        reason_code=existing_rec.status.value,
                        message=f"Alert exists in terminal/dormant state {existing_rec.status.value}.",
                    )

            # Check activation watermark
            is_suppressed = False
            suppression_reason = None
            if self.config.activation_watermark:
                event_time = req.completed_at or req.created_date or datetime.now(timezone.utc)
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
                if event_time < self.config.activation_watermark:
                    is_suppressed = True
                    suppression_reason = "WATERMARK_SUPPRESSED"

            # Format titles and bodies
            request_num = req.name or f"GR-{canon_req_id[-6:]}"
            title, body = format_notification_content(
                kind, action_code_val, request_num, self.config.preferred_language
            )

            # Allocate new record
            nid = f"a05{self._next_notification_number:012d}AAA"
            self._next_notification_number += 1

            new_record = RequestNotificationRecord(
                id=nid,
                alert_key=alert_key,
                source_event_key=source_event_key,
                event_kind=kind,
                generation_request_id=canon_req_id,
                recipient_user_id=candidate_user_id,
                channel=NotificationChannel.SALESFORCE_CUSTOM_NOTIFICATION,
                status=NotificationStatus.SUPPRESSED if is_suppressed else NotificationStatus.PENDING,
                payload_fingerprint=payload_fingerprint,
                source_revision=1,
                artifact_set_id=set_id,
                artifact_set_version=set_ver,
                failure_episode_id=failure_episode_id if kind == NotificationKind.ACTION_REQUIRED else None,
                action_code=action_code_val,
                attempts=0,
                max_attempts=self.config.max_retry_attempts,
                target_record_id=canon_req_id,
                notification_title=title,
                notification_body=body,
                safe_error_code=suppression_reason,
            )

            self.notifications[nid] = new_record
            self.alert_keys[alert_key] = nid

            return AdmissionResult(
                outcome=AdmissionOutcome.SUPPRESSED if is_suppressed else AdmissionOutcome.ADMITTED,
                alert_key=alert_key,
                notification_id=nid,
                reason_code=suppression_reason or "SUCCESS",
                message="Notification successfully admitted." if not is_suppressed else "Suppressed by watermark.",
            )

    # --- Dispatcher Logic (S04) ---

    def dispatch_pending(self, notification_id: str | None = None) -> list[DispatchResult]:
        """Dispatch admitted notifications through guarded pre-send fence and serialized claim."""
        with self._lock:
            candidates: list[RequestNotificationRecord] = []
            if notification_id:
                rec = self.notifications.get(notification_id)
                if rec and rec.status in (NotificationStatus.PENDING, NotificationStatus.RETRY_WAIT):
                    candidates.append(rec)
            else:
                for rec in self.notifications.values():
                    if rec.status == NotificationStatus.PENDING:
                        candidates.append(rec)
                    elif rec.status == NotificationStatus.RETRY_WAIT:
                        if rec.next_retry_at is None or rec.next_retry_at <= datetime.now(timezone.utc):
                            candidates.append(rec)

            results: list[DispatchResult] = []
            for rec in candidates:
                res = self._dispatch_single(rec)
                results.append(res)
            return results

    def _dispatch_single(self, rec: RequestNotificationRecord) -> DispatchResult:
        """Execute atomic dispatch for a single ledger record under lock."""
        # Check obsolescence / suppression
        req = self.submission_service.get_request(rec.generation_request_id)
        if not req:
            rec.status = NotificationStatus.BLOCKED
            rec.safe_error_code = "REQUEST_DELETED"
            return DispatchResult(rec.id, rec.alert_key, rec.status, rec.attempts, safe_error_code=rec.safe_error_code)

        # If a ready event was admitted, but request is no longer Ready_for_Review or was superseded
        if rec.event_kind == NotificationKind.READY:
            ui_state = self.review_service.get_review_ui_state(
                req.id, candidate_user_id=rec.recipient_user_id
            )
            # Pre-send fence: re-verify recipient file accessibility
            if not ui_state.all_formats_delivered or not ui_state.cards["docx"].is_accessible or not ui_state.cards["pdf"].is_accessible:
                rec.status = NotificationStatus.BLOCKED
                rec.safe_error_code = "RECIPIENT_ACCESS_REVOKED"
                rec.updated_at = datetime.now(timezone.utc)
                return DispatchResult(rec.id, rec.alert_key, rec.status, rec.attempts, safe_error_code=rec.safe_error_code)

        elif rec.event_kind == NotificationKind.ACTION_REQUIRED:
            # If request transitioned to Ready_for_Review, suppress stale failure notification
            if req.status == "Ready_for_Review":
                rec.status = NotificationStatus.SUPPRESSED
                rec.safe_error_code = "SUPERSEDED_BY_READY"
                rec.updated_at = datetime.now(timezone.utc)
                return DispatchResult(rec.id, rec.alert_key, rec.status, rec.attempts, safe_error_code=rec.safe_error_code)

        # Serialized claim
        rec.status = NotificationStatus.DISPATCHING
        rec.attempt_identifier = str(uuid.uuid4())
        rec.attempts += 1
        rec.dispatched_at = datetime.now(timezone.utc)
        rec.updated_at = datetime.now(timezone.utc)

        # Invoke sender callback
        send_success = False
        exception_type: str | None = None
        if self.sender_callback:
            try:
                send_success = self.sender_callback(rec)
            except Exception as e:
                send_success = False
                exception_type = type(e).__name__
        else:
            # Default simulated send succeeds
            send_success = True

        if send_success:
            # Invariant: Recording Accepted does NOT mutate request status or approve document
            rec.status = NotificationStatus.ACCEPTED
            rec.accepted_at = datetime.now(timezone.utc)
            rec.safe_error_code = None
            rec.uncertainty_reason = None
            rec.updated_at = datetime.now(timezone.utc)
            return DispatchResult(rec.id, rec.alert_key, rec.status, rec.attempts)

        # Failure / Exception handling
        if exception_type == "TimeoutError" or exception_type == "AmbiguousSendError":
            # Fence into UNCERTAIN: potential unacknowledged send, never auto-retry!
            rec.status = NotificationStatus.UNCERTAIN
            rec.uncertainty_reason = "Send response unconfirmed; possible network delivery"
            rec.safe_error_code = "AMBIGUOUS_SEND"
            rec.updated_at = datetime.now(timezone.utc)
            return DispatchResult(
                rec.id, rec.alert_key, rec.status, rec.attempts,
                safe_error_code=rec.safe_error_code, uncertainty_reason=rec.uncertainty_reason
            )

        # Proven non-send failure -> retry or dead letter
        if rec.attempts < rec.max_attempts:
            rec.status = NotificationStatus.RETRY_WAIT
            delay_mins = self.config.initial_retry_delay_minutes * (2 ** (rec.attempts - 1))
            rec.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=delay_mins)
            rec.safe_error_code = exception_type or "SEND_FAILED"
            rec.updated_at = datetime.now(timezone.utc)
            return DispatchResult(rec.id, rec.alert_key, rec.status, rec.attempts, safe_error_code=rec.safe_error_code)
        else:
            rec.status = NotificationStatus.DEAD_LETTER
            rec.safe_error_code = "MAX_RETRIES_EXCEEDED"
            rec.updated_at = datetime.now(timezone.utc)
            return DispatchResult(rec.id, rec.alert_key, rec.status, rec.attempts, safe_error_code=rec.safe_error_code)

    # --- Recovery and Admin Operations ---

    def retry_due(self) -> list[DispatchResult]:
        """Retry notifications in RETRY_WAIT whose backoff delay has elapsed."""
        return self.dispatch_pending()

    def reconcile_uncertain(self, alert_key: str, resolution: str) -> RequestNotificationRecord:
        """Operator reconciliation of uncertain sends: confirm_accepted, suppress, or force_retry."""
        with self._lock:
            rec = self.get_notification_by_alert_key(alert_key)
            if not rec:
                raise ValueError(f"AlertKey {alert_key} not found")
            if rec.status != NotificationStatus.UNCERTAIN:
                raise ValueError(f"Record is not in Uncertain status (is {rec.status})")

            if resolution == "confirm_accepted":
                rec.status = NotificationStatus.ACCEPTED
                rec.accepted_at = datetime.now(timezone.utc)
                rec.uncertainty_reason = "Manually confirmed accepted by operator"
            elif resolution == "suppress":
                rec.status = NotificationStatus.SUPPRESSED
                rec.uncertainty_reason = "Manually suppressed by operator"
            elif resolution == "force_retry":
                rec.status = NotificationStatus.PENDING
                rec.uncertainty_reason = "Operator authorized retry after verified non-delivery"
            else:
                raise ValueError(f"Invalid resolution: {resolution}")

            rec.updated_at = datetime.now(timezone.utc)
            return rec

    def get_backlog_summary(self) -> dict[str, int]:
        """Return counts by status."""
        with self._lock:
            summary = {s.value: 0 for s in NotificationStatus}
            for rec in self.notifications.values():
                summary[rec.status.value] += 1
            return summary

    def resolve_failure_episode(self, request_id: str) -> None:
        """Mark an active failure episode as resolved when the issue has been addressed."""
        with self._lock:
            canon_req_id = canonicalize_salesforce_id(request_id)
            self._active_failure_episodes.pop((self.org_id, canon_req_id), None)
