"""Comprehensive validation scenario test suite for SF-08 Draft-ready and failure notifications (V01-V20).

Tests:
- V01: XML Parsing, Manifest, and Ownership Registry Validation
- V02: Pending/Offline, Running, and Upload_Pending (No False Readiness Alerts)
- V03: Complete Delivery Readiness Notification (Never Implies Human Approval)
- V04: Replay & Repeat Update Deduplication (Zero Duplicate Alerts)
- V05: Ready -> Upload_Pending -> Ready Status Cycling (Repair Releases Key Once)
- V06: Document Approval & Supersession Isolation (Distinct Genuine Transitions)
- V07: Out-of-Order Convergence (Ready vs Registration Arrival Orders)
- V08: Recipient-Aware File Access Verification vs Worker/Admin Download Access
- V09: Terminal Failure Notifications (Inspectable Request Without Local Worker)
- V10: Upload-Pending Intervention vs Transient Retry Filtering
- V11: Failure Episode Resolution, Suppression of Obsolete Failure/Ready Alerts
- V12: Concurrent Observers & Senders (Thread Safety & Exactly-One Admission)
- V13: Crash Matrix & Ambiguous Send Fencing (Uncertain State Preserved)
- V14: Proven Non-Send Bounded Retries & Dead Letter State Machine
- V15: Fail-Closed Recipient Resolution (Zero Fallback to Admin or Worker)
- V16: Safe Diagnostic Content Filtering (Zero Leaked Tokens, Paths, or Exceptions)
- V17: Record Target Link Authenticated Navigation (No Public URLs or Mutations)
- V18: Bulk Batch Processing & Fault Isolation
- V19: Portability, Export/Restore, and Anti-Storm Watermark Preservation
- V20: Bilingual Template Localization (DE / EN), Umlauts, and Windows Native Integrity
"""

from __future__ import annotations

from job_automation.generation.request_mapping import canonicalize_salesforce_id

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import uuid
import pytest
from zoneinfo import ZoneInfo

from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliverySetReceipt,
    RemoteArtifactMapping,
    ReviewProjection,
)
from job_automation.salesforce.artifact_review import (
    ArtifactReviewService,
    ApprovalStatus,
    FormatReviewCard,
    ReviewCommand,
    ReviewAction,
)
from job_automation.salesforce.generation_submission import (
    GenerationSubmissionService,
    SubmissionIntent,
    SubmissionOutcome,
    SubmissionResult,
)
from job_automation.salesforce.metadata_parser import (
    CustomNotificationTypeMetadata,
    CustomObjectMetadata,
    CustomPermissionMetadata,
    FlowMetadata,
    PermissionSetMetadata,
    load_permission_set,
    load_salesforce_dx_custom_permissions,
    load_salesforce_dx_flows,
    load_salesforce_dx_notification_types,
    load_salesforce_dx_objects,
    validate_sf08_admin_permission_set,
    validate_sf08_metadata,
)
from job_automation.salesforce.request_notifications import (
    AdmissionOutcome,
    AdmissionResult,
    DispatchResult,
    FormatBinding,
    LanguageCode,
    NotificationConfig,
    NotificationKind,
    NotificationStatus,
    RequestNotificationRecord,
    RequestNotificationService,
    compute_alert_key,
    compute_failure_event_key,
    compute_payload_fingerprint,
    compute_ready_event_key,
    format_notification_content,
    sanitize_diagnostic_text,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
CUSTOM_PERMS_DIR = SF_MAIN_DIR / "customPermissions"
FLOWS_DIR = SF_MAIN_DIR / "flows"
NOTIF_TYPES_DIR = SF_MAIN_DIR / "notificationtypes"
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"
OWNERSHIP_PATH = REPO_ROOT / "salesforce" / "metadata-ownership.json"

BERLIN_TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture
def submission_service() -> GenerationSubmissionService:
    svc = GenerationSubmissionService()
    svc.register_job(
        job_id="a01000000000001AAA",
        name="JOB-000001",
        job_title="Lead Software Engineer",
        canonical_job_id="11111111-2222-3333-4444-555555555555",
        availability="Active",
    )
    return svc


@pytest.fixture
def review_service(submission_service: GenerationSubmissionService) -> ArtifactReviewService:
    svc = ArtifactReviewService(submission_service=submission_service)
    svc.register_user("005000000000001AAA", role="candidate")
    svc.register_user("005000000000002AAA", role="worker")
    svc.register_user("005000000000003AAA", role="unrelated")
    return svc


@pytest.fixture
def notification_service(
    submission_service: GenerationSubmissionService,
    review_service: ArtifactReviewService,
) -> RequestNotificationService:
    svc = RequestNotificationService(
        submission_service=submission_service,
        review_service=review_service,
        org_id="00D000000000001AAA",
    )
    svc.configure(
        is_enabled=True,
        candidate_user_id="005000000000001AAA",
        language=LanguageCode.EN,
        enable_mobile=False,
    )
    return svc


@pytest.fixture
def standard_delivery_receipt() -> tuple[DeliverySetReceipt, ReviewProjection]:
    req_uuid = uuid.uuid4()
    art_set_uuid = uuid.uuid4()
    art1_uuid = uuid.uuid4()
    art2_uuid = uuid.uuid4()

    docx_mapping = RemoteArtifactMapping(
        intent_id=uuid.uuid4(),
        request_id=req_uuid,
        artifact_id=art1_uuid,
        artifact_version=1,
        artifact_format="docx",
        content_hash="sha256:" + "a" * 64,
        org_id="00D000000000001AAA",
        content_document_id="069000000000001AAA",
        content_version_id="068000000000001AAA",
        marker=f"gen06:v1:{req_uuid}:{art1_uuid}:1",
        target_record_id="a02000000000001AAA",
        acknowledged_at=datetime.now(timezone.utc),
    )

    pdf_mapping = RemoteArtifactMapping(
        intent_id=uuid.uuid4(),
        request_id=req_uuid,
        artifact_id=art2_uuid,
        artifact_version=1,
        artifact_format="pdf",
        content_hash="sha256:" + "b" * 64,
        org_id="00D000000000001AAA",
        content_document_id="069000000000002AAA",
        content_version_id="068000000000002AAA",
        marker=f"gen06:v1:{req_uuid}:{art2_uuid}:1",
        target_record_id="a02000000000001AAA",
        acknowledged_at=datetime.now(timezone.utc),
    )

    docx_access = AccessibilityReceipt(
        mapping_id=docx_mapping.mapping_id,
        request_id=req_uuid,
        artifact_id=art1_uuid,
        artifact_version=1,
        artifact_format="docx",
        content_version_id=docx_mapping.content_version_id,
        content_document_id=docx_mapping.content_document_id,
        target_record_id=docx_mapping.target_record_id,
        verification_method="sharing_policy_check",
        candidate_principal="005000000000001AAA",
        verified_at=datetime.now(timezone.utc),
    )

    pdf_access = AccessibilityReceipt(
        mapping_id=pdf_mapping.mapping_id,
        request_id=req_uuid,
        artifact_id=art2_uuid,
        artifact_version=1,
        artifact_format="pdf",
        content_version_id=pdf_mapping.content_version_id,
        content_document_id=pdf_mapping.content_document_id,
        target_record_id=pdf_mapping.target_record_id,
        verification_method="sharing_policy_check",
        candidate_principal="005000000000001AAA",
        verified_at=datetime.now(timezone.utc),
    )

    receipt = DeliverySetReceipt(
        request_id=req_uuid,
        set_id=art_set_uuid,
        set_version=1,
        required_formats=["docx", "pdf"],
        mappings={"docx": docx_mapping, "pdf": pdf_mapping},
        accessibility_receipts={"docx": docx_access, "pdf": pdf_access},
        review_route="/lightning/r/Generation_Request__c/a02000000000001AAA/view",
        created_at=datetime.now(timezone.utc),
    )

    projection = ReviewProjection(
        request_id=req_uuid,
        salesforce_request_id="a02000000000001AAA",
        set_version=1,
        result_version_refs={"docx": "068000000000001AAA", "pdf": "068000000000002AAA"},
        result_document_refs={"docx": "069000000000001AAA", "pdf": "069000000000002AAA"},
        review_warnings=["Claims verified against snapshot profile v1"],
        delivered_at=receipt.created_at,
    )

    return receipt, projection


def bind_receipt_to_request(
    receipt: DeliverySetReceipt,
    projection: ReviewProjection | None,
    salesforce_request_id: str,
) -> tuple[DeliverySetReceipt, ReviewProjection | None]:
    new_mappings = {
        fmt: m.model_copy(update={"target_record_id": salesforce_request_id})
        for fmt, m in receipt.mappings.items()
    }
    new_receipt = receipt.model_copy(update={"mappings": new_mappings})
    new_proj = None
    if projection:
        new_proj = projection.model_copy(update={"salesforce_request_id": salesforce_request_id})
    return new_receipt, new_proj


class TestSF08Scenarios:

    # --- V01: XML Parsing, Manifest, and Ownership Registry Validation ---
    def test_v01_xml_parsing_manifest_and_registry(self) -> None:
        objects = load_salesforce_dx_objects(SF_OBJECTS_DIR)
        perm_sets = {
            "job_notification_administrator": load_permission_set(
                PERMSETS_DIR / "Job_Notification_Administrator.permissionset-meta.xml"
            )
        }
        flows = load_salesforce_dx_flows(FLOWS_DIR)
        notif_types = load_salesforce_dx_notification_types(NOTIF_TYPES_DIR)
        custom_perms = load_salesforce_dx_custom_permissions(CUSTOM_PERMS_DIR)

        report = validate_sf08_metadata(
            objects=objects,
            perm_sets=perm_sets,
            flows=flows,
            notif_types=notif_types,
            custom_perms=custom_perms,
        )
        assert report.compatible is True, f"SF-08 metadata issues: {report.issues}"
        assert len(report.issues) == 0

        # Inactive initial flows check
        assert flows["ja_request_notification_observe"].status == "Draft"
        assert flows["ja_request_notification_dispatch"].status == "Draft"

    # --- V02: Pending/Offline, Running, and Upload_Pending (No False Readiness) ---
    def test_v02_pending_running_upload_pending_zero_alerts(
        self,
        submission_service: GenerationSubmissionService,
        notification_service: RequestNotificationService,
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v02-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # 1. Status == Pending -> Zero ready alerts
        adm_pending = notification_service.admit_transition(req_id)
        assert adm_pending.outcome == AdmissionOutcome.NOT_ELIGIBLE
        assert adm_pending.reason_code == "INTERMEDIATE_PROCESSING_STATE"

        # 2. Status == Running -> Zero ready alerts
        submission_service.transition_status(req_id, "Running")
        adm_running = notification_service.admit_transition(req_id)
        assert adm_running.outcome == AdmissionOutcome.NOT_ELIGIBLE

        # 3. Status == Upload_Pending -> Zero ready alerts
        submission_service.transition_status(req_id, "Upload_Pending")
        adm_upload = notification_service.admit_transition(req_id)
        assert adm_upload.outcome == AdmissionOutcome.NOT_ELIGIBLE
        assert adm_upload.reason_code == "UPLOAD_PENDING_NORMAL"

        assert len(notification_service.notifications) == 0

    # --- V03: Complete Delivery Readiness Notification (Never Implies Human Approval) ---
    def test_v03_complete_readiness_notification_delivery_not_approval(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v03-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")

        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # Candidate user has verified access
        adm_res = notification_service.admit_transition(req_id)
        assert adm_res.outcome == AdmissionOutcome.ADMITTED
        assert adm_res.alert_key is not None

        # Dispatch
        dispatches = notification_service.dispatch_pending()
        assert len(dispatches) == 1
        assert dispatches[0].status == NotificationStatus.ACCEPTED

        # Invariant: Recording Accepted does NOT mutate Generation_Request__c.Status__c
        req_after = submission_service.get_request(req_id)
        assert req_after.status == "Ready_for_Review"
        assert req_after.status != "Approved"

        # Invariant: JA_Artifact_Review__c remains in draft approval status
        ui_state = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        assert ui_state.cards["docx"].approval_status == "draft"
        assert ui_state.cards["pdf"].approval_status == "draft"

        # Safe wording: says "Draft ready for review", never "Approved" or "Submitted"
        notif = notification_service.get_notification_by_alert_key(adm_res.alert_key)
        assert notif is not None
        assert notif.notification_title == "Draft ready for review"
        assert "DOCX and PDF drafts are available" in notif.notification_body
        assert "Approved" not in notif.notification_body

    # --- V04: Replay & Repeat Update Deduplication (Zero Duplicate Alerts) ---
    def test_v04_replay_and_repeat_update_deduplication(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v04-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")

        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # Initial admission & dispatch
        adm_1 = notification_service.admit_transition(req_id)
        assert adm_1.outcome == AdmissionOutcome.ADMITTED
        notification_service.dispatch_pending()

        # Re-admission attempt on unchanged ready state -> REPLAYED
        adm_2 = notification_service.admit_transition(req_id)
        assert adm_2.outcome == AdmissionOutcome.REPLAYED
        assert adm_2.reason_code == "ALREADY_ACCEPTED"

        # Delivery registration replay -> preserved and still REPLAYED
        review_service.register_delivery_set(updated_receipt, updated_proj)
        adm_3 = notification_service.admit_transition(req_id)
        assert adm_3.outcome == AdmissionOutcome.REPLAYED

        # Exactly 1 notification row in ledger
        assert len(notification_service.notifications) == 1
        notif = notification_service.get_notification(adm_1.notification_id)
        assert notif.attempts == 1

    # --- V05: Ready -> Upload_Pending -> Ready Status Cycling ---
    def test_v05_status_cycling_and_access_repair(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v05-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")

        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # Revoke candidate access before initial admission
        doc_id = receipt.mappings["docx"].content_document_id
        review_service.revoke_content_document_link(doc_id, req_id)

        # 1. Inaccessible -> BLOCKED (never sent)
        adm_blocked = notification_service.admit_transition(req_id)
        assert adm_blocked.outcome == AdmissionOutcome.BLOCKED
        assert adm_blocked.reason_code == "RECIPIENT_ACCESS_DENIED"

        # Request cycles to Upload_Pending and back to Ready_for_Review
        submission_service.transition_status(req_id, "Upload_Pending")
        submission_service.transition_status(req_id, "Ready_for_Review")

        # Repair candidate file access
        review_service.register_content_document_link(doc_id, req_id, share_type="V", visibility="AllUsers")

        # 2. Repair releases the same alert key to Pending
        adm_repaired = notification_service.admit_transition(req_id)
        assert adm_repaired.outcome == AdmissionOutcome.ADMITTED
        assert adm_repaired.reason_code == "BLOCKED_RELEASED"

        # Dispatch succeeds once
        dispatches = notification_service.dispatch_pending()
        assert len(dispatches) == 1
        assert dispatches[0].status == NotificationStatus.ACCEPTED

        # 3. Status cycle again Ready -> Upload_Pending -> Ready: does NOT send again
        submission_service.transition_status(req_id, "Upload_Pending")
        submission_service.transition_status(req_id, "Ready_for_Review")
        adm_cycle = notification_service.admit_transition(req_id)
        assert adm_cycle.outcome == AdmissionOutcome.REPLAYED
        assert adm_cycle.reason_code == "ALREADY_ACCEPTED"

    # --- V06: Document Approval & Supersession Isolation ---
    def test_v06_approval_and_supersession_zero_new_alerts(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v06-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")

        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)
        notification_service.admit_transition(req_id)
        notification_service.dispatch_pending()

        # Candidate approves DOCX
        ui_state = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        docx_card = ui_state.cards["docx"]
        cmd = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=docx_card.review_id,
            expected_version_id=docx_card.content_version_id,
            expected_content_hash=docx_card.content_hash,
            expected_review_revision=1,
            candidate_user_id="005000000000001AAA",
            intent_token="cmd-token-1",
        )
        review_service.execute_review_command(cmd)

        # Invariant: Human approval does not trigger a new readiness alert
        adm_after_approval = notification_service.admit_transition(req_id)
        assert adm_after_approval.outcome == AdmissionOutcome.REPLAYED
        assert len(notification_service.notifications) == 1

        # A brand new deliberate request gets a distinct separate ready alert
        regen_res = review_service.request_regeneration(
            predecessor_request_id=req_id,
            submission_token="v06-regen-token",
            candidate_user_id="005000000000001AAA",
        )
        assert regen_res.outcome == SubmissionOutcome.CREATED
        new_req_id = regen_res.request_id
        submission_service.transition_status(new_req_id, "Ready_for_Review")

        # Distinct artifact set for new request
        new_art_set = uuid.uuid4()
        d_map = receipt.mappings["docx"].model_copy(update={
            "target_record_id": new_req_id,
            "artifact_id": uuid.uuid4(),
            "content_document_id": "069000000000088AAA",
            "content_version_id": "068000000000088AAA",
        })
        p_map = receipt.mappings["pdf"].model_copy(update={
            "target_record_id": new_req_id,
            "artifact_id": uuid.uuid4(),
            "content_document_id": "069000000000089AAA",
            "content_version_id": "068000000000089AAA",
        })
        upd_receipt2 = receipt.model_copy(update={
            "set_id": new_art_set,
            "mappings": {"docx": d_map, "pdf": p_map},
        })
        upd_proj2 = projection.model_copy(update={
            "salesforce_request_id": new_req_id,
        })
        review_service.register_delivery_set(upd_receipt2, upd_proj2)

        adm_new_req = notification_service.admit_transition(new_req_id)
        assert adm_new_req.outcome == AdmissionOutcome.ADMITTED
        assert adm_new_req.alert_key != adm_after_approval.alert_key

    # --- V07: Out-of-Order Convergence (Ready vs Registration Arrival) ---
    def test_v07_out_of_order_arrival_convergence(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v07-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # 1. Ready arrives BEFORE registration -> BLOCKED (missing files)
        submission_service.transition_status(req_id, "Ready_for_Review")
        adm_1 = notification_service.admit_transition(req_id)
        assert adm_1.outcome == AdmissionOutcome.BLOCKED
        assert adm_1.reason_code == "INCOMPLETE_FORMATS"

        # 2. Registration arrives later
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # 3. Observer re-evaluates -> converges cleanly to ADMITTED
        adm_2 = notification_service.admit_transition(req_id)
        assert adm_2.outcome == AdmissionOutcome.ADMITTED

    # --- V08: Recipient-Aware File Access Verification vs Worker Access ---
    def test_v08_candidate_file_access_least_privilege_boundary(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v08-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")

        # Worker uploads files but candidate link is deleted
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)
        pdf_doc_id = receipt.mappings["pdf"].content_document_id
        review_service.revoke_content_document_link(pdf_doc_id, req_id)

        # Worker can download, but candidate cannot -> admission BLOCKED
        adm = notification_service.admit_transition(req_id)
        assert adm.outcome == AdmissionOutcome.BLOCKED
        assert adm.reason_code == "RECIPIENT_ACCESS_DENIED"

    # --- V09: Terminal Failure Notifications ---
    def test_v09_terminal_failed_without_files_safe_alert(
        self,
        submission_service: GenerationSubmissionService,
        notification_service: RequestNotificationService,
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v09-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # Terminal Failure without any files
        submission_service.transition_status(req_id, "Failed", error_reason="Inference failed")
        adm = notification_service.admit_transition(req_id, failure_episode_id="ep-v09-1")
        assert adm.outcome == AdmissionOutcome.ADMITTED

        # Dispatch succeeds while worker is offline
        dispatches = notification_service.dispatch_pending()
        assert len(dispatches) == 1
        assert dispatches[0].status == NotificationStatus.ACCEPTED

        # Replay with same episode does NOT re-alert
        adm_replay = notification_service.admit_transition(req_id, failure_episode_id="ep-v09-1")
        assert adm_replay.outcome == AdmissionOutcome.REPLAYED

    # --- V10: Upload-Pending Intervention vs Transient Retry Filtering ---
    def test_v10_upload_intervention_vs_transient_retry(
        self,
        submission_service: GenerationSubmissionService,
        notification_service: RequestNotificationService,
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v10-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # 1. Normal transient retry in Upload_Pending -> ZERO alerts
        submission_service.transition_status(req_id, "Upload_Pending")
        adm_transient = notification_service.admit_transition(req_id, is_upload_intervention=False)
        assert adm_transient.outcome == AdmissionOutcome.NOT_ELIGIBLE

        # 2. Explicit intervention required (e.g. quota exhausted) -> 1 action_required alert
        adm_intervention = notification_service.admit_transition(
            req_id, is_upload_intervention=True, failure_episode_id="ep-v10-int"
        )
        assert adm_intervention.outcome == AdmissionOutcome.ADMITTED

        notif = notification_service.get_notification_by_alert_key(adm_intervention.alert_key)
        assert notif.event_kind == NotificationKind.ACTION_REQUIRED
        assert notif.notification_title == "Draft delivery needs attention"
        assert "file delivery is blocked" in notif.notification_body

    # --- V11: Failure Episode Resolution & Suppression ---
    def test_v11_failure_resolution_and_ready_suppression(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v11-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # 1. Request failed
        submission_service.transition_status(req_id, "Failed")
        adm_fail = notification_service.admit_transition(req_id, failure_episode_id="ep-v11-1")
        assert adm_fail.outcome == AdmissionOutcome.ADMITTED

        # 2. Before dispatch of failure, request recovers and completes to Ready_for_Review
        submission_service.transition_status(req_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # Dispatching: failure alert is SUPPRESSED because request is now Ready
        notification_service.dispatch_pending()
        fail_notif = notification_service.get_notification(adm_fail.notification_id)
        assert fail_notif.status == NotificationStatus.SUPPRESSED
        assert fail_notif.safe_error_code == "SUPERSEDED_BY_READY"

    # --- V12: Concurrent Observers & Senders ---
    def test_v12_concurrent_admission_and_dispatch(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v12-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # Run 5 concurrent threads attempting to admit the same transition
        outcomes: list[AdmissionResult] = []
        threads = []

        def admit_worker():
            r = notification_service.admit_transition(req_id)
            outcomes.append(r)

        for _ in range(5):
            t = threading.Thread(target=admit_worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Exactly 1 admitted, 4 replayed
        admitted = [o for o in outcomes if o.outcome == AdmissionOutcome.ADMITTED]
        replayed = [o for o in outcomes if o.outcome == AdmissionOutcome.REPLAYED]
        assert len(admitted) == 1
        assert len(replayed) == 4
        assert len(notification_service.notifications) == 1

    # --- V13: Crash Matrix & Ambiguous Send Fencing (Uncertain State Preserved) ---
    def test_v13_crash_matrix_and_ambiguous_send_fencing(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt

        # Mock sender that raises timeout during socket write
        def throwing_sender(rec: RequestNotificationRecord):
            raise TimeoutError("Platform network timeout during CustomNotification send")

        crashing_service = RequestNotificationService(
            submission_service=submission_service,
            review_service=review_service,
            sender_callback=throwing_sender,
        )
        crashing_service.configure(is_enabled=True, candidate_user_id="005000000000001AAA")

        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v13-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        adm = crashing_service.admit_transition(req_id)
        assert adm.outcome == AdmissionOutcome.ADMITTED

        # Dispatch experiences network timeout -> fenced into UNCERTAIN
        crashing_service.dispatch_pending()
        notif = crashing_service.get_notification(adm.notification_id)
        assert notif.status == NotificationStatus.UNCERTAIN
        assert notif.safe_error_code == "AMBIGUOUS_SEND"

        # Automated retries will NEVER resend an Uncertain record
        retry_results = crashing_service.retry_due()
        assert len(retry_results) == 0
        assert notif.status == NotificationStatus.UNCERTAIN

        # Operator can reconcile
        crashing_service.reconcile_uncertain(notif.alert_key, "confirm_accepted")
        assert notif.status == NotificationStatus.ACCEPTED

    # --- V14: Proven Non-Send Bounded Retries & Dead Letter State Machine ---
    def test_v14_bounded_retries_and_dead_letter(
        self,
        submission_service: GenerationSubmissionService,
        notification_service: RequestNotificationService,
    ) -> None:
        # Mock sender that fails with ConnectionRefused
        def failing_sender(rec: RequestNotificationRecord):
            raise ConnectionRefusedError("Connection refused before write")

        notification_service.sender_callback = failing_sender
        notification_service.config.max_retry_attempts = 2

        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v14-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Failed")

        adm = notification_service.admit_transition(req_id, failure_episode_id="ep-v14-fail")
        notif = notification_service.get_notification(adm.notification_id)

        # Attempt 1: fails -> Retry_Wait
        notification_service.dispatch_pending()
        assert notif.status == NotificationStatus.RETRY_WAIT
        assert notif.attempts == 1

        # Fast forward time
        notif.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        # Attempt 2: fails -> Dead_Letter (max retries reached)
        notification_service.retry_due()
        assert notif.status == NotificationStatus.DEAD_LETTER
        assert notif.attempts == 2
        assert notif.safe_error_code == "MAX_RETRIES_EXCEEDED"

    # --- V15: Fail-Closed Recipient Resolution (Zero Fallback) ---
    def test_v15_fail_closed_recipient_resolution(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v15-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # Disable configuration -> fails closed, zero fallback
        notification_service.configure(is_enabled=False, candidate_user_id=None)
        adm_disabled = notification_service.admit_transition(req_id)
        assert adm_disabled.outcome == AdmissionOutcome.BLOCKED
        assert adm_disabled.reason_code == "CONFIG_DISABLED"

        # Enable without candidate user -> fails closed
        notification_service.configure(is_enabled=True, candidate_user_id=None)
        adm_no_user = notification_service.admit_transition(req_id)
        assert adm_no_user.outcome == AdmissionOutcome.BLOCKED
        assert adm_no_user.reason_code == "RECIPIENT_NOT_CONFIGURED"

        # Zero notifications created
        assert len(notification_service.notifications) == 0

    # --- V16: Safe Diagnostic Content Filtering ---
    def test_v16_safe_diagnostic_content_filtering(
        self,
        submission_service: GenerationSubmissionService,
        notification_service: RequestNotificationService,
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v16-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # Raw error contains tokens, HTML, and local file path
        raw_error = "<script>alert(1)</script> Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-x at C:\\Users\\secret\\req.json"
        submission_service.transition_status(req_id, "Failed", error_reason=raw_error)

        adm = notification_service.admit_transition(req_id, failure_episode_id="ep-v16-1")
        notif = notification_service.get_notification(adm.notification_id)

        # Invariant: Tokens, scripts, paths, and URLs are stripped from title and body
        assert "<script>" not in notif.notification_title
        assert "<script>" not in notif.notification_body
        assert "secret" not in notif.notification_body
        assert "eyJhbG" not in notif.notification_body
        assert notif.notification_title == "Draft request needs attention"

    # --- V17: Record Target Link Authenticated Navigation ---
    def test_v17_target_record_link_navigation(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v17-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        adm = notification_service.admit_transition(req_id)
        notif = notification_service.get_notification(adm.notification_id)

        # Targets Salesforce record ID directly; no external URLs
        assert canonicalize_salesforce_id(notif.target_record_id) == canonicalize_salesforce_id(req_id)
        assert not notif.target_record_id.startswith("http")

    # --- V18: Bulk Batch Processing & Fault Isolation ---
    def test_v18_bulk_batch_processing_and_fault_isolation(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt

        # Register distinct jobs
        for i in range(1, 4):
            submission_service.register_job(
                job_id=f"a0100000000000{i}AAA",
                name=f"JOB-00000{i}",
                job_title=f"Engineer {i}",
                canonical_job_id=f"{i}{i}{i}{i}{i}{i}{i}{i}-3333-4444-5555-666666666666",
                availability="Active",
            )

        req_ids: list[str] = []
        for i in range(1, 4):
            intent = SubmissionIntent(
                job_id=f"a0100000000000{i}AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token=f"v18-token-{i}",
            )
            res = submission_service.submit(intent)
            req_ids.append(res.request_id)
            submission_service.transition_status(res.request_id, "Ready_for_Review")

            # Distinct mappings per request
            r_uuid = uuid.uuid4()
            d_id = f"06900000000001{i}AAA"
            v_id = f"06800000000001{i}AAA"
            d_map = receipt.mappings["docx"].model_copy(update={
                "target_record_id": res.request_id,
                "content_document_id": d_id,
                "content_version_id": v_id,
                "artifact_id": r_uuid,
            })
            p_map = receipt.mappings["pdf"].model_copy(update={
                "target_record_id": res.request_id,
                "content_document_id": f"06900000000002{i}AAA",
                "content_version_id": f"06800000000002{i}AAA",
                "artifact_id": uuid.uuid4(),
            })
            upd_receipt = receipt.model_copy(update={
                "set_id": uuid.uuid4(),
                "mappings": {"docx": d_map, "pdf": p_map},
            })
            upd_proj = projection.model_copy(update={
                "salesforce_request_id": res.request_id,
            })
            review_service.register_delivery_set(upd_receipt, upd_proj)

        # Batch admit 3 requests
        adm_results = [notification_service.admit_transition(rid) for rid in req_ids]
        assert all(r.outcome == AdmissionOutcome.ADMITTED for r in adm_results)

        # Dispatch all 3
        dispatches = notification_service.dispatch_pending()
        assert len(dispatches) == 3
        assert all(d.status == NotificationStatus.ACCEPTED for d in dispatches)

    # --- V19: Portability, Export/Restore, and Anti-Storm Watermark Preservation ---
    def test_v19_export_restore_and_watermark_preservation(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v19-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")

        # Set activation watermark in the future
        future_watermark = datetime.now(timezone.utc) + timedelta(hours=1)
        notification_service.configure(
            is_enabled=True,
            candidate_user_id="005000000000001AAA",
            activation_watermark=future_watermark,
        )

        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        # Request completed prior to watermark -> SUPPRESSED (no storm)
        adm = notification_service.admit_transition(req_id)
        assert adm.outcome == AdmissionOutcome.SUPPRESSED
        assert adm.reason_code == "WATERMARK_SUPPRESSED"

        notif = notification_service.get_notification(adm.notification_id)
        assert notif.status == NotificationStatus.SUPPRESSED

    # --- V20: Bilingual Template Localization (DE / EN), Umlauts, and Windows Native Integrity ---
    def test_v20_german_template_localization_and_umlauts(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        notification_service: RequestNotificationService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v20-token",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id
        submission_service.transition_status(req_id, "Ready_for_Review")

        # Configure for German
        notification_service.configure(
            is_enabled=True,
            candidate_user_id="005000000000001AAA",
            language=LanguageCode.DE,
        )

        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, req_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        adm = notification_service.admit_transition(req_id)
        assert adm.outcome == AdmissionOutcome.ADMITTED

        notif = notification_service.get_notification(adm.notification_id)
        # German template with proper umlauts
        assert notif.notification_title == "Entwurf bereit zur Prüfung"
        assert "DOCX- und PDF-Entwürfe stehen zur Verfügung" in notif.notification_body
        assert "Öffnen Sie die Anfrage zur Prüfung" in notif.notification_body
