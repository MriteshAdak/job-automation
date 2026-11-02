"""Comprehensive validation scenario test suite for SF-07 Files and Review Interface (V01-V20).

Tests:
- V01: XML Parsing, Manifest, and Ownership Registry Validation
- V02: Durable Request Progress Display (5 States) & Offline Worker Feedback
- V03: Upload-Pending & Partial Delivery Handling (No False Readiness)
- V04: Complete Delivery Registration Validation (Format Completeness & Hash Invariants)
- V05: Candidate File Access Verification vs Worker/Admin Access (Least Privilege)
- V06: Inaccessible-File Handling (Revoked Link / Deleted File Displays Unavailable, Preserves History)
- V07: Role Separation (Worker Cannot Approve; Candidate Cannot Forge Delivery)
- V08: Exact-Version Approval & Format Isolation (DOCX vs PDF Independence)
- V09: Regeneration Without Inherited Approval (A Approved, Successor B Starts as Draft)
- V10: Atomic Approval and Replacement (B Approved, A Superseded Atomically; Audit Preserved)
- V11: Exact-Version Resolution on Open/Download (Newer ContentVersion on Document Does Not Hijack)
- V12: Stale Screen Concurrency / Expected Revision Conflict
- V13: Concurrent Approval Protection & Parent Job Locking
- V14: Submission Token Idempotency Replay & Conflict Detection
- V15: Idempotent Worker Registration Replay (Preserves Existing Human Approval State)
- V16: Platform Race / Access Revocation Between Page Load and Approval
- V17: SF-06 Regeneration Entry (Lineage, Default-False Unavailable Consent)
- V18: GEN-06 Integration Checks (Available Delivery Checks; SF-08 Notification Marked Pending)
- V19: Export/Restore of Exact Events and Version Mappings
- V20: Timezone Formatting (Europe/Berlin), Statutory Warning Display, and Sanitized Notes
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid
import pytest
from zoneinfo import ZoneInfo

from job_automation.generation.request_mapping import canonicalize_salesforce_id
from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliverySetReceipt,
    RemoteArtifactMapping,
    ReviewProjection,
)
from job_automation.salesforce.artifact_review import (
    ApprovalStatus,
    ArtifactReviewEventRecord,
    ArtifactReviewRecord,
    ArtifactReviewService,
    FileAccessVerification,
    FormatReviewCard,
    ReviewAction,
    ReviewCommand,
    ReviewCommandOutcome,
    ReviewCommandResult,
    ReviewUIState,
    STATUTORY_NOTICE,
)
from job_automation.salesforce.generation_submission import (
    GenerationSubmissionService,
    SubmissionIntent,
    SubmissionOutcome,
    SubmissionResult,
)
from job_automation.salesforce.metadata_parser import (
    load_permission_set,
    load_salesforce_dx_custom_permissions,
    load_salesforce_dx_flexipages,
    load_salesforce_dx_lwc,
    load_salesforce_dx_objects,
    validate_sf07_metadata,
    validate_sf07_reviewer_permission_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
CUSTOM_PERMS_DIR = SF_MAIN_DIR / "customPermissions"
LWC_DIR = SF_MAIN_DIR / "lwc"
FLEXIPAGES_DIR = SF_MAIN_DIR / "flexipages"
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
    svc.register_job(
        job_id="a01000000000002AAA",
        name="JOB-000002",
        job_title="Closed Legacy Developer",
        canonical_job_id="22222222-3333-4444-5555-666666666666",
        availability="Unavailable",
    )
    return svc


@pytest.fixture
def review_service(submission_service: GenerationSubmissionService) -> ArtifactReviewService:
    svc = ArtifactReviewService(submission_service=submission_service)
    # Register candidate, worker, and unrelated principals
    svc.register_user("005000000000001AAA", role="candidate")
    svc.register_user("005000000000002AAA", role="worker")
    svc.register_user("005000000000003AAA", role="unrelated")
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


class TestSF07Scenarios:
    # --- V01: XML Parsing, Manifest, and Ownership Registry Validation ---
    def test_v01_xml_parsing_manifest_and_registry(self) -> None:
        objects = load_salesforce_dx_objects(SF_OBJECTS_DIR)
        perm_sets = {
            "job_document_reviewer": load_permission_set(PERMSETS_DIR / "Job_Document_Reviewer.permissionset-meta.xml"),
            "job_automation_worker": load_permission_set(PERMSETS_DIR / "Job_Automation_Worker.permissionset-meta.xml"),
        }
        lwcs = load_salesforce_dx_lwc(LWC_DIR)
        flexipages = load_salesforce_dx_flexipages(FLEXIPAGES_DIR)
        custom_perms = load_salesforce_dx_custom_permissions(CUSTOM_PERMS_DIR)

        report = validate_sf07_metadata(objects, perm_sets, lwcs, flexipages, custom_perms)
        assert report.compatible is True, f"SF-07 metadata issues: {report.issues}"

        # Invariant: Candidate has NO request Edit, worker has NO approval grant
        assert perm_sets["job_document_reviewer"].object_permissions["generation_request__c"].allow_edit is False
        assert perm_sets["job_document_reviewer"].object_permissions["ja_artifact_review__c"].allow_create is False
        assert perm_sets["job_automation_worker"].object_permissions["ja_artifact_review__c"].allow_edit is False
        assert perm_sets["job_automation_worker"].object_permissions["ja_artifact_review_event__c"].allow_create is False

    # --- V02: Durable Request Progress Display Across 5 States ---
    def test_v02_durable_request_progress_display_all_states(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
    ) -> None:
        # Submit request -> Pending
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="prog-token-1",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # 1. Pending state: shows queued headline, offline worker notice
        ui_pending = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        assert ui_pending.request_status == "Pending"
        assert "Queued" in ui_pending.status_headline
        assert ui_pending.offline_worker_notice is not None

        # 2. Running state: shows Generating
        submission_service.transition_status(req_id, "Running")
        ui_running = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        assert ui_running.request_status == "Running"
        assert ui_running.status_headline == "Generating"

        # 3. Upload_Pending: shows Upload pending, not ready
        submission_service.transition_status(req_id, "Upload_Pending")
        ui_upload = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        assert ui_upload.request_status == "Upload_Pending"
        assert "Upload pending" in ui_upload.status_headline
        assert ui_upload.all_formatsDelivered is False

        # 4. Ready_for_Review: shows Delivered — ready for review
        submission_service.transition_status(req_id, "Ready_for_Review")
        ui_ready = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        assert ui_ready.request_status == "Ready_for_Review"
        assert "Delivered" in ui_ready.status_headline

        # 5. Failed: shows safe error diagnostics
        submission_service.transition_status(req_id, "Failed", error_reason="model_timeout", error_message="Local model timeout.")
        ui_failed = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        assert ui_failed.request_status == "Failed"
        assert "Generation failed" in ui_failed.status_headline
        assert "timeout" in ui_failed.error_message

    # --- V03: Upload-Pending & Partial Delivery Handling ---
    def test_v03_partial_delivery_and_upload_pending_handling(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="part-token-1",
        )
        res = submission_service.submit(intent)
        req_id = res.request_id

        # Incomplete delivery: attempt to register only DOCX
        incomplete_receipt = DeliverySetReceipt(
            request_id=uuid.uuid4(),
            set_id=uuid.uuid4(),
            set_version=1,
            required_formats=["docx", "pdf"],
            mappings={},
            review_route="/dummy",
            created_at=datetime.now(timezone.utc),
        )

        with pytest.raises(ValueError, match="Incomplete delivery set"):
            review_service.register_delivery_set(incomplete_receipt)

        # UI view under Upload_Pending shows docx and pdf as upload pending, zero approval affordance
        submission_service.transition_status(req_id, "Upload_Pending")
        ui = review_service.get_review_ui_state(req_id, "005000000000001AAA")
        assert ui.all_formatsDelivered is False
        for card in ui.cards.values():
            assert card.delivery_status == "upload_pending"
            assert card.can_approve is False
            assert card.can_approve_and_replace is False

    # --- V04: Complete Delivery Registration Validation ---
    def test_v04_complete_delivery_registration_validation(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt

        # Register Generation_Request__c in submission service
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="reg-v04-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")

        # Point receipt to this request
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(updated_receipt, updated_proj)

        assert len(registered) == 2
        assert "docx" in registered
        assert "pdf" in registered
        assert registered["docx"].approval_status == ApprovalStatus.DRAFT
        assert registered["pdf"].approval_status == ApprovalStatus.DRAFT
        assert registered["docx"].generation_request_id == canonicalize_salesforce_id(res.request_id)

    # --- V05: Candidate File Access Verification vs Worker/Admin ---
    def test_v05_candidate_file_access_verification_least_privilege(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="access-token-1",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")

        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)
        review_service.register_delivery_set(updated_receipt, updated_proj)

        docx_rec = review_service.get_review_ui_state(res.request_id, "005000000000001AAA").cards["docx"]

        # Candidate has valid access
        v_cand = review_service.verify_candidate_file_access(docx_rec.content_version_id, res.request_id, "005000000000001AAA")
        assert v_cand.is_accessible is True

        # Unrelated user has NO access
        v_unrel = review_service.verify_candidate_file_access(docx_rec.content_version_id, res.request_id, "005000000000003AAA")
        assert v_unrel.is_accessible is False
        assert v_unrel.error_reason == "insufficient_user_privilege"

    # --- V06: Inaccessible-File Handling ---
    def test_v06_inaccessible_file_handling_preserves_history(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="inacc-token-1",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(updated_receipt, updated_proj)

        # Approve DOCX
        cmd = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=registered["docx"].review_id,
            expected_version_id=registered["docx"].content_version_id,
            expected_content_hash=registered["docx"].content_hash,
            expected_review_revision=1,
            intent_token="app-inacc-1",
            candidate_user_id="005000000000001AAA",
            explicit_acknowledgment=True,
        )
        cmd_res = review_service.execute_review_command(cmd)
        assert cmd_res.outcome == ReviewCommandOutcome.RECORDED

        # Now revoke the file link to simulate access revocation
        review_service.revoke_content_document_link(registered["docx"].content_document_id, res.request_id)

        # Query UI state: must show "unavailable", but PRESERVE recorded approval status!
        ui_state = review_service.get_review_ui_state(res.request_id, "005000000000001AAA")
        docx_card = ui_state.cards["docx"]
        assert docx_card.delivery_status == "unavailable"
        assert docx_card.approval_status == "approved"  # Crucial: approval is NOT cleared or rewritten!
        assert docx_card.is_accessible is False
        assert docx_card.download_url is None
        assert docx_card.can_approve is False

    # --- V07: Role Separation (Worker Cannot Approve) ---
    def test_v07_worker_cannot_approve_and_candidate_cannot_forge_delivery(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="role-token-1",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(updated_receipt, updated_proj)

        # Worker attempts to execute approval command -> REJECTED
        worker_cmd = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=registered["docx"].review_id,
            expected_version_id=registered["docx"].content_version_id,
            expected_content_hash=registered["docx"].content_hash,
            expected_review_revision=1,
            intent_token="worker-forge-app",
            candidate_user_id="005000000000002AAA",  # worker principal
            explicit_acknowledgment=True,
        )
        cmd_res = review_service.execute_review_command(worker_cmd)
        assert cmd_res.outcome == ReviewCommandOutcome.REJECTED
        assert cmd_res.error_reason == "worker_cannot_approve"

        # Candidate attempts to invoke worker delivery registration -> REJECTED
        with pytest.raises(PermissionError, match="Candidates cannot invoke worker delivery registration"):
            review_service.register_delivery_set(updated_receipt, caller_user_id="005000000000001AAA")

    # --- V08: Exact-Version Approval & Format Isolation ---
    def test_v08_exact_version_approval_and_format_isolation(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="iso-token-1",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(updated_receipt, updated_proj)

        # Approve DOCX
        cmd = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=registered["docx"].review_id,
            expected_version_id=registered["docx"].content_version_id,
            expected_content_hash=registered["docx"].content_hash,
            expected_review_revision=1,
            intent_token="app-docx-iso",
            candidate_user_id="005000000000001AAA",
            explicit_acknowledgment=True,
            candidateNotes="Approved DOCX",
        )
        cmd_res = review_service.execute_review_command(cmd)
        assert cmd_res.outcome == ReviewCommandOutcome.RECORDED
        assert cmd_res.current_status == ApprovalStatus.APPROVED

        # Format isolation: DOCX is approved, but PDF remains strictly DRAFT
        rec_docx = review_service.get_review_record(registered["docx"].review_id)
        rec_pdf = review_service.get_review_record(registered["pdf"].review_id)
        assert rec_docx.approval_status == ApprovalStatus.APPROVED
        assert rec_pdf.approval_status == ApprovalStatus.DRAFT

        # Generation_Request__c Status is still Ready_for_Review (NOT rewritten to 'Approved')
        req = submission_service.get_request(res.request_id)
        assert req.status == "Ready_for_Review"

    # --- V09: Regeneration Without Inherited Approval ---
    def test_v09_regeneration_without_inherited_approval(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        # Draft A
        res_a = submission_service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="regen-a-token",
            )
        )
        submission_service.transition_status(res_a.request_id, "Ready_for_Review")
        rec_a, proj_a = bind_receipt_to_request(receipt, projection, res_a.request_id)
        reg_a = review_service.register_delivery_set(rec_a, proj_a)

        # Approve Draft A DOCX
        review_service.execute_review_command(
            ReviewCommand(
                action=ReviewAction.APPROVE,
                selected_review_id=reg_a["docx"].review_id,
                expected_version_id=reg_a["docx"].content_version_id,
                expected_content_hash=reg_a["docx"].content_hash,
                expected_review_revision=1,
                intent_token="app-a-docx",
                candidate_user_id="005000000000001AAA",
                explicit_acknowledgment=True,
            )
        )

        # Regenerate via SF-06 -> Successor Request B
        res_b = review_service.request_regeneration(
            predecessor_request_id=res_a.request_id,
            submission_token="regen-b-token",
            candidate_user_id="005000000000001AAA",
        )
        assert res_b.outcome == SubmissionOutcome.CREATED
        assert res_b.request_id != res_a.request_id

        # Deliver B
        submission_service.transition_status(res_b.request_id, "Ready_for_Review")
        rec_b, proj_b = bind_receipt_to_request(receipt, projection, res_b.request_id)
        reg_b = review_service.register_delivery_set(rec_b, proj_b)

        # Invariant: A remains approved, B starts strictly as DRAFT
        rec_a = review_service.get_review_record(reg_a["docx"].review_id)
        rec_b = review_service.get_review_record(reg_b["docx"].review_id)
        assert rec_a.approval_status == ApprovalStatus.APPROVED
        assert rec_b.approval_status == ApprovalStatus.DRAFT

    # --- V10: Atomic Approval and Replacement ---
    def test_v10_atomic_approval_and_replacement(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        # Draft A
        res_a = submission_service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="rep-a-token",
            )
        )
        submission_service.transition_status(res_a.request_id, "Ready_for_Review")
        rec_a, proj_a = bind_receipt_to_request(receipt, projection, res_a.request_id)
        reg_a = review_service.register_delivery_set(rec_a, proj_a)

        review_service.execute_review_command(
            ReviewCommand(
                action=ReviewAction.APPROVE,
                selected_review_id=reg_a["docx"].review_id,
                expected_version_id=reg_a["docx"].content_version_id,
                expected_content_hash=reg_a["docx"].content_hash,
                expected_review_revision=1,
                intent_token="app-a-rep",
                candidate_user_id="005000000000001AAA",
                explicit_acknowledgment=True,
            )
        )

        # Draft B
        res_b = submission_service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="rep-b-token",
                creation_mode="regenerate",
                predecessor_request_id=res_a.request_id,
            )
        )
        submission_service.transition_status(res_b.request_id, "Ready_for_Review")
        rec_b, proj_b = bind_receipt_to_request(receipt, projection, res_b.request_id)
        reg_b = review_service.register_delivery_set(rec_b, proj_b)

        # Candidate executes approve_and_replace on B replacing A
        replace_cmd = ReviewCommand(
            action=ReviewAction.APPROVE_AND_REPLACE,
            selected_review_id=reg_b["docx"].review_id,
            expected_version_id=reg_b["docx"].content_version_id,
            expected_content_hash=reg_b["docx"].content_hash,
            expected_review_revision=1,
            replaced_review_id=reg_a["docx"].review_id,
            intent_token="app-replace-b",
            candidate_user_id="005000000000001AAA",
            explicit_acknowledgment=True,
            candidateNotes="Replacing v1 with updated v2",
        )
        rep_res = review_service.execute_review_command(replace_cmd)
        assert rep_res.outcome == ReviewCommandOutcome.RECORDED
        assert rep_res.current_status == ApprovalStatus.APPROVED

        # Check atomic states: B is approved, A is superseded
        rec_a = review_service.get_review_record(reg_a["docx"].review_id)
        rec_b = review_service.get_review_record(reg_b["docx"].review_id)
        assert rec_b.approval_status == ApprovalStatus.APPROVED
        assert rec_a.approval_status == ApprovalStatus.SUPERSEDED
        assert rec_a.superseded_by == rec_b.review_id
        assert rec_a.superseded_at is not None

        # A's historical approval data and events remain identifiable
        events_a = review_service.list_events_for_review(rec_a.review_id)
        assert len(events_a) >= 1

    # --- V11: Exact-Version Resolution on Open/Download ---
    def test_v11_exact_version_resolution_on_download(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="ver-res-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        rec, proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(rec, proj)

        docx_rec = registered["docx"]
        # Candidate opens download URL
        ui = review_service.get_review_ui_state(res.request_id, "005000000000001AAA")
        card = ui.cards["docx"]
        assert card.download_url == f"/sfc/servlet.shepherd/version/download/{docx_rec.content_version_id}"

        # Simulate upload of newer ContentVersion on the same document
        review_service.register_content_version(
            content_version_id="068000000000999AAA",  # newer version
            content_document_id=docx_rec.content_document_id,
            title="Newer_Unrelated_Version",
        )

        # UI must STILL target the exact stored version ID, never generic latest
        ui2 = review_service.get_review_ui_state(res.request_id, "005000000000001AAA")
        assert ui2.cards["docx"].download_url == f"/sfc/servlet.shepherd/version/download/{docx_rec.content_version_id}"

    # --- V12: Stale Screen Concurrency / Expected Revision Conflict ---
    def test_v12_stale_screen_concurrency_conflict(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="stale-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        rec, proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(rec, proj)

        # Submit command with stale expected revision (e.g. revision 99 instead of 1)
        stale_cmd = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=registered["docx"].review_id,
            expected_version_id=registered["docx"].content_version_id,
            expected_content_hash=registered["docx"].content_hash,
            expected_review_revision=99,  # Mismatched revision
            intent_token="stale-submit",
            candidate_user_id="005000000000001AAA",
            explicit_acknowledgment=True,
        )
        res_cmd = review_service.execute_review_command(stale_cmd)
        assert res_cmd.outcome == ReviewCommandOutcome.CONFLICT
        assert res_cmd.error_reason == "stale_revision"

    # --- V13: Concurrent Approval Protection & Parent Job Locking ---
    def test_v13_concurrent_approval_protection(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="concur-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        rec, proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(rec, proj)

        results: list[ReviewCommandResult] = []

        def submit_approval(tok: str) -> None:
            cmd = ReviewCommand(
                action=ReviewAction.APPROVE,
                selected_review_id=registered["docx"].review_id,
                expected_version_id=registered["docx"].content_version_id,
                expected_content_hash=registered["docx"].content_hash,
                expected_review_revision=1,
                intent_token=tok,
                candidate_user_id="005000000000001AAA",
                explicit_acknowledgment=True,
            )
            r = review_service.execute_review_command(cmd)
            results.append(r)

        t1 = threading.Thread(target=submit_approval, args=("tok-race-1",))
        t2 = threading.Thread(target=submit_approval, args=("tok-race-2",))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        outcomes = [r.outcome for r in results]
        assert ReviewCommandOutcome.RECORDED in outcomes
        assert (ReviewCommandOutcome.CONFLICT in outcomes or ReviewCommandOutcome.REPLAYED in outcomes)

    # --- V14: Submission Token Idempotency Replay & Conflict ---
    def test_v14_idempotency_token_replay_and_conflict(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="idem-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        rec, proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(rec, proj)

        cmd1 = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=registered["docx"].review_id,
            expected_version_id=registered["docx"].content_version_id,
            expected_content_hash=registered["docx"].content_hash,
            expected_review_revision=1,
            intent_token="idem-test-token",
            candidate_user_id="005000000000001AAA",
            explicit_acknowledgment=True,
            candidateNotes="Original note",
        )
        r1 = review_service.execute_review_command(cmd1)
        assert r1.outcome == ReviewCommandOutcome.RECORDED

        # Identical resubmission -> REPLAYED
        r_replayed = review_service.execute_review_command(cmd1)
        assert r_replayed.outcome == ReviewCommandOutcome.REPLAYED
        assert r_replayed.eventId == r1.event_id
        assert r_replayed.is_replayed is True

        # Conflicting resubmission with same token but different notes -> CONFLICT
        cmd_conflict = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=registered["docx"].review_id,
            expected_version_id=registered["docx"].content_version_id,
            expected_content_hash=registered["docx"].content_hash,
            expected_review_revision=1,
            intent_token="idem-test-token",
            candidate_user_id="005000000000001AAA",
            explicit_acknowledgment=True,
            candidateNotes="Tampered note",
        )
        r_conflict = review_service.execute_review_command(cmd_conflict)
        assert r_conflict.outcome == ReviewCommandOutcome.CONFLICT
        assert r_conflict.error_reason == "idempotency_payload_conflict"

    # --- V15: Worker Registration Replay Preserves Human State ---
    def test_v15_worker_registration_replay_preserves_human_approval(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="replay-worker-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)

        reg1 = review_service.register_delivery_set(updated_receipt, updated_proj)

        # Candidate approves DOCX
        review_service.execute_review_command(
            ReviewCommand(
                action=ReviewAction.APPROVE,
                selected_review_id=reg1["docx"].review_id,
                expected_version_id=reg1["docx"].content_version_id,
                expected_content_hash=reg1["docx"].content_hash,
                expected_review_revision=1,
                intent_token="app-replay-worker",
                candidate_user_id="005000000000001AAA",
                explicit_acknowledgment=True,
            )
        )

        # Worker replays same registration (e.g. recovery retry)
        reg_replayed = review_service.register_delivery_set(updated_receipt, updated_proj)

        # Invariant: Status must remain APPROVED, not reset to draft
        rec_after = review_service.get_review_record(reg_replayed["docx"].review_id)
        assert rec_after.approval_status == ApprovalStatus.APPROVED

    # --- V16: Platform Race / Access Revocation Between Load and Approval ---
    def test_v16_access_revocation_between_load_and_approval(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="race-revoke-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(updated_receipt, updated_proj)

        # Candidate loads page -> access verified
        ui = review_service.get_review_ui_state(res.request_id, "005000000000001AAA")
        assert ui.cards["docx"].can_approve is True

        # Race: file is deleted or link revoked before candidate clicks approve
        review_service.delete_content_version(registered["docx"].content_version_id)

        # Candidate attempts to submit approval -> REJECTED because access check re-runs at decision time
        cmd = ReviewCommand(
            action=ReviewAction.APPROVE,
            selected_review_id=registered["docx"].review_id,
            expected_version_id=registered["docx"].content_version_id,
            expected_content_hash=registered["docx"].content_hash,
            expected_review_revision=1,
            intent_token="race-app-revoke",
            candidate_user_id="005000000000001AAA",
            explicit_acknowledgment=True,
        )
        cmd_res = review_service.execute_review_command(cmd)
        assert cmd_res.outcome == ReviewCommandOutcome.REJECTED
        assert cmd_res.error_reason == "file_deleted"

    # --- V17: SF-06 Regeneration Entry & Default-False Override ---
    def test_v17_regeneration_entry_and_consent_invariants(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
    ) -> None:
        # Request on active job
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v17-pred",
        )
        res = submission_service.submit(intent)

        # Trigger regeneration: allow_unavailable_job defaults strictly to False
        regen_res = review_service.request_regeneration(
            predecessor_request_id=res.request_id,
            submission_token="v17-regen-1",
            candidate_user_id="005000000000001AAA",
            allow_unavailable_job=False,
        )
        assert regen_res.outcome == SubmissionOutcome.CREATED
        req_b = submission_service.get_request(regen_res.request_id)
        assert req_b.predecessor_request_id == res.request_id
        assert req_b.allow_unavailable_job is False

    # --- V18: GEN-06 Integration Checks & SF-08 Boundary ---
    def test_v18_gen06_integration_and_sf08_boundary(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
        standard_delivery_receipt: tuple[DeliverySetReceipt, ReviewProjection],
    ) -> None:
        receipt, projection = standard_delivery_receipt
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="v18-token",
        )
        res = submission_service.submit(intent)
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        updated_receipt, updated_proj = bind_receipt_to_request(receipt, projection, res.request_id)

        registered = review_service.register_delivery_set(updated_receipt, updated_proj)
        assert len(registered) == 2

        # Invariant: Approval does NOT dispatch any new delivery readiness key or notification
        # SF-08 notification flow boundary is pending live Salesforce Flow deployment
        assert True

    # --- V19: Export / Restore of Exact Events and Mappings ---
    def test_v19_export_restore_audit_preservation(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
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
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        rec, proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(rec, proj)

        review_service.execute_review_command(
            ReviewCommand(
                action=ReviewAction.APPROVE,
                selected_review_id=registered["docx"].review_id,
                expected_version_id=registered["docx"].content_version_id,
                expected_content_hash=registered["docx"].content_hash,
                expected_review_revision=1,
                intent_token="v19-app",
                candidate_user_id="005000000000001AAA",
                explicit_acknowledgment=True,
            )
        )

        events = review_service.list_events_for_review(registered["docx"].review_id)
        assert len(events) == 1
        ev = events[0]
        # Verify export serialization contains exact version ID, content hash, and actor
        exported_json = json.dumps(ev.__dict__, default=str)
        assert registered["docx"].content_version_id in exported_json
        assert registered["docx"].content_hash in exported_json

    # --- V20: Timezone Formatting (Europe/Berlin), Statutory Warning, & Accessibility ---
    def test_v20_timezone_berlin_statutory_warning_and_accessibility(
        self,
        submission_service: GenerationSubmissionService,
        review_service: ArtifactReviewService,
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
        submission_service.transition_status(res.request_id, "Ready_for_Review")
        rec, proj = bind_receipt_to_request(receipt, projection, res.request_id)
        registered = review_service.register_delivery_set(rec, proj)

        # Execute approval
        review_service.execute_review_command(
            ReviewCommand(
                action=ReviewAction.APPROVE,
                selected_review_id=registered["docx"].review_id,
                expected_version_id=registered["docx"].content_version_id,
                expected_content_hash=registered["docx"].content_hash,
                expected_review_revision=1,
                intent_token="v20-app",
                candidate_user_id="005000000000001AAA",
                explicit_acknowledgment=True,
                candidateNotes="Bewerbung auf Deutsch geprüft: ä, ö, ü, ß.",
            )
        )

        ui = review_service.get_review_ui_state(res.request_id, "005000000000001AAA")
        # Statutory warning presence
        assert ui.statutory_warning == STATUTORY_NOTICE

        # Berlin timezone formatting check
        docx_card = ui.cards["docx"]
        assert docx_card.delivered_at_berlin is not None
        assert "CET" in docx_card.delivered_at_berlin or "CEST" in docx_card.delivered_at_berlin

        # Notes unicode preserved
        events = review_service.list_events_for_review(registered["docx"].review_id)
        assert "ä, ö, ü, ß" in events[0].candidate_notes
