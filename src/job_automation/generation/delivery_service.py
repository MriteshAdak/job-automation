"""Delivery service coordinator managing intent persistence, upload reconciliation, linking, and accessibility gating (GEN-06-S04, S05)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.delivery_access import verify_candidate_access
from job_automation.generation.delivery_ports import (
    ArtifactDeliveryServicePort,
    SalesforceFilesGatewayPort,
)
from job_automation.generation.delivery_reconciliation import (
    ReconciliationOutcome,
    reconcile_or_create_link,
    reconcile_upload_by_marker,
)
from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliveryAttempt,
    DeliveryIntent,
    DeliverySetReceipt,
    RemoteArtifactMapping,
    build_reconciliation_marker,
)
from job_automation.generation.delivery_settings import DeliverySettings
from job_automation.generation.records import ArtifactDeliveryRecord
from job_automation.generation.render_records import ArtifactSet, compute_file_sha256
from job_automation.salesforce.file_records import CreateContentVersionRequest

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class DeliveryService(ArtifactDeliveryServicePort):
    """Coordinates durable artifact delivery to Salesforce Files and verifies candidate accessibility."""

    def __init__(
        self,
        engine: StorageEngine,
        gateway: SalesforceFilesGatewayPort,
        settings: DeliverySettings | None = None,
    ) -> None:
        self.engine = engine
        self.gateway = gateway
        self.settings = settings or DeliverySettings()

    def deliver_or_reconcile(
        self,
        request: GenerationRequest,
        artifact_set: ArtifactSet,
        salesforce_request_id: str,
        canonical_salesforce_id: str | None = None,
    ) -> tuple[DeliverySetReceipt | None, ClassifiedError | None]:
        """Deliver all required formats of an ArtifactSet to Salesforce Files or reconcile existing uploads."""
        if not salesforce_request_id:
            return None, ClassifiedError.validation(
                "Cannot deliver artifacts: missing remote salesforce_request_id"
            )

        # 1. Verify complete local artifact set
        if not artifact_set.is_complete:
            return None, ClassifiedError.validation(
                f"ArtifactSet {artifact_set.set_id} is incomplete: missing formats from required {artifact_set.required_formats}"
            )

        for fmt in artifact_set.required_formats:
            if fmt not in artifact_set.artifacts:
                return None, ClassifiedError.validation(
                    f"Required format '{fmt}' absent from ArtifactSet"
                )
            receipt = artifact_set.artifacts[fmt]
            p = Path(receipt.local_path)
            if not p.is_file():
                return None, ClassifiedError.validation(
                    f"Physical artifact file missing on disk: {receipt.local_path}"
                )
            actual_hash = compute_file_sha256(p)
            if actual_hash != receipt.content_hash:
                return None, ClassifiedError.validation(
                    f"Physical artifact file corrupted or tampered: hash '{actual_hash}' != expected '{receipt.content_hash}'"
                )

        mappings: dict[str, RemoteArtifactMapping] = {}
        access_receipts: dict[str, AccessibilityReceipt] = {}

        # 2. Iterate each required format
        for fmt in artifact_set.required_formats:
            receipt = artifact_set.artifacts[fmt]
            marker = build_reconciliation_marker(
                request.request_id, receipt.artifact_id, receipt.version
            )

            # Check if format is already delivered and verified
            existing_mapping = self.engine.artifact_deliveries.get_remote_mapping(
                self.settings.expected_org_id,
                request.request_id,
                receipt.artifact_id,
                receipt.version,
            )
            existing_access = self.engine.artifact_deliveries.get_accessibility_receipt(
                request.request_id, receipt.version, fmt
            )

            if existing_mapping and existing_access:
                mappings[fmt] = existing_mapping
                access_receipts[fmt] = existing_access
                continue

            # 3. Create & commit DeliveryIntent BEFORE any network I/O
            now_utc = datetime.now(timezone.utc)
            intent = DeliveryIntent(
                intent_id=uuid.uuid4(),
                org_id=self.settings.expected_org_id,
                salesforce_request_id=salesforce_request_id,
                canonical_salesforce_id=canonical_salesforce_id,
                request_id=request.request_id,
                artifact_set_id=artifact_set.set_id,
                artifact_id=receipt.artifact_id,
                artifact_version=receipt.version,
                artifact_format=fmt,
                content_hash=receipt.content_hash,
                size_bytes=receipt.size_bytes,
                local_path=receipt.local_path,
                reconciliation_marker=marker,
                status="pending",
                created_at=now_utc,
                updated_at=now_utc,
            )
            intent = self.engine.artifact_deliveries.save_intent(intent)

            # 4. Check if upload already succeeded remotely (reconciliation before resend)
            recon = reconcile_upload_by_marker(self.gateway, intent)
            content_version_id: str | None = None
            content_document_id: str | None = None

            if recon.outcome == ReconciliationOutcome.EXACT_MATCH:
                content_version_id = recon.content_version_id
                content_document_id = recon.content_document_id
            elif recon.outcome == ReconciliationOutcome.CONFLICT:
                self.engine.artifact_deliveries.update_intent_status(intent.intent_id, "blocked")
                return None, ClassifiedError.validation(
                    f"Reconciliation conflict for marker '{marker}': {recon.reason}"
                )
            elif recon.outcome == ReconciliationOutcome.INCONCLUSIVE:
                # Do NOT upload; remain in upload_pending
                self.engine.artifact_deliveries.update_intent_status(intent.intent_id, "uncertain")
                return None, ClassifiedError.transient_network(
                    f"Reconciliation inconclusive for marker '{marker}': {recon.reason}"
                )
            else:
                # PROVEN_ABSENT: Safe to send physical upload
                self.engine.artifact_deliveries.update_intent_status(intent.intent_id, "sending")
                attempt_seq = len(self.engine.artifact_deliveries.list_attempts_for_intent(intent.intent_id)) + 1
                attempt = DeliveryAttempt(
                    attempt_id=uuid.uuid4(),
                    intent_id=intent.intent_id,
                    request_id=request.request_id,
                    attempt_sequence=attempt_seq,
                    operation_kind="upload",
                    phase="sending",
                    started_at=datetime.now(timezone.utc),
                    status="started",
                )
                self.engine.artifact_deliveries.record_attempt(attempt)

                with open(receipt.local_path, "rb") as f:
                    file_bytes = f.read()

                upload_req = CreateContentVersionRequest(
                    title=f"{request.document_type.value.upper()}_{fmt.upper()}_{request.request_id}",
                    path_on_client=f"{receipt.artifact_id}.{fmt}",
                    version_data=file_bytes,
                    reconciliation_marker=marker,
                    content_hash=receipt.content_hash,
                    first_publish_location_id=salesforce_request_id,
                )
                res = self.gateway.create_content_version(upload_req)
                attempt_completed_at = datetime.now(timezone.utc)

                if res.is_failure:
                    fail = res.failure
                    err = fail.error if fail else ClassifiedError.transient_network("Upload failed")
                    attempt_failed = attempt.model_copy(
                        update={
                            "completed_at": attempt_completed_at,
                            "status": "failed",
                            "error_json": {"message": err.message, "category": err.category.value},
                        }
                    )
                    self.engine.artifact_deliveries.record_attempt(attempt_failed)

                    if fail and fail.remote_outcome == "unknown":
                        self.engine.artifact_deliveries.update_intent_status(intent.intent_id, "uncertain")
                        # Try immediate reconciliation
                        post_recon = reconcile_upload_by_marker(self.gateway, intent)
                        if post_recon.outcome == ReconciliationOutcome.EXACT_MATCH:
                            content_version_id = post_recon.content_version_id
                            content_document_id = post_recon.content_document_id
                        else:
                            return None, err
                    else:
                        self.engine.artifact_deliveries.update_intent_status(
                            intent.intent_id,
                            "blocked" if err.category == ErrorCategory.CAPACITY else "failed",
                        )
                        return None, err
                else:
                    assert res.value is not None
                    content_version_id = res.value.content_version_id
                    content_document_id = res.value.content_document_id
                    attempt_ok = attempt.model_copy(
                        update={
                            "completed_at": attempt_completed_at,
                            "status": "completed",
                            "outcome_evidence": {
                                "content_version_id": content_version_id,
                                "content_document_id": content_document_id,
                            },
                        }
                    )
                    self.engine.artifact_deliveries.record_attempt(attempt_ok)

            if not content_version_id:
                return None, ClassifiedError.transient_network(
                    f"Delivery failed: missing content_version_id for {fmt}"
                )

            # Fallback document ID lookup if needed
            if not content_document_id:
                v_res = self.gateway.get_content_version(content_version_id)
                if v_res.is_success and v_res.value:
                    content_document_id = v_res.value.content_document_id

            if not content_document_id:
                return None, ClassifiedError.transient_network(
                    f"Delivery failed: ContentDocumentId unresolvable for version {content_version_id}"
                )

            # 5. Link reconciliation & creation
            link_id, link_err = reconcile_or_create_link(
                gateway=self.gateway,
                content_document_id=content_document_id,
                target_record_id=salesforce_request_id,
            )
            if link_err or not link_id:
                # Link failed; remain upload_pending without deleting uploaded file
                self.engine.artifact_deliveries.update_intent_status(intent.intent_id, "uploaded")
                return None, link_err or ClassifiedError.transient_network("Linking failed")

            # Link canonical job if provided
            if canonical_salesforce_id and canonical_salesforce_id != salesforce_request_id:
                reconcile_or_create_link(
                    gateway=self.gateway,
                    content_document_id=content_document_id,
                    target_record_id=canonical_salesforce_id,
                )

            # 6. Candidate accessibility check
            mapping = RemoteArtifactMapping(
                mapping_id=uuid.uuid4(),
                intent_id=intent.intent_id,
                request_id=request.request_id,
                artifact_id=receipt.artifact_id,
                artifact_version=receipt.version,
                artifact_format=fmt,
                content_hash=receipt.content_hash,
                org_id=self.settings.expected_org_id,
                content_document_id=content_document_id,
                content_version_id=content_version_id,
                marker=marker,
                target_record_id=salesforce_request_id,
                link_id=link_id,
                acknowledged_at=datetime.now(timezone.utc),
            )
            access_receipt, access_err = verify_candidate_access(
                gateway=self.gateway,
                mapping=mapping,
                verification_method=self.settings.access_verification_method,
            )
            if access_err or not access_receipt:
                self.engine.artifact_deliveries.update_intent_status(intent.intent_id, "linked")
                return None, access_err or ClassifiedError.from_category(
                    ErrorCategory.PERMISSION, "Candidate access verification failed"
                )

            # 7. Atomically commit format delivery to storage
            artifact_row = self.engine.artifacts.get_artifact(receipt.artifact_id)
            if artifact_row is None:
                artifact_row = Artifact(
                    artifact_id=receipt.artifact_id,
                    request_id=request.request_id,
                    artifact_version=receipt.version,
                    format=fmt,
                    local_path=receipt.local_path,
                    content_hash=receipt.content_hash,
                    size_bytes=receipt.size_bytes,
                    remote_file_id=content_version_id,
                    delivery_status="delivered",
                    approval_status=DocumentApproval.DRAFT,
                    reconciliation_marker=marker,
                    created_at=receipt.created_at,
                )

            delivery_slot = ArtifactDeliveryRecord(
                delivery_id=uuid.uuid4(),
                request_id=request.request_id,
                artifact_format=fmt,
                artifact_id=receipt.artifact_id,
                artifact_hash=receipt.content_hash,
                remote_file_id=content_version_id,
                delivery_status="delivered",
                delivered_at=datetime.now(timezone.utc),
            )

            self.engine.artifact_deliveries.commit_format_delivery(
                intent=intent,
                mapping=mapping,
                access_receipt=access_receipt,
                artifact=artifact_row,
                delivery_slot=delivery_slot,
            )

            mappings[fmt] = mapping
            access_receipts[fmt] = access_receipt

        # 8. All required formats delivered and verified accessible!
        review_route = self.settings.review_route_template.format(
            salesforce_request_id=salesforce_request_id
        )
        set_receipt = DeliverySetReceipt(
            set_receipt_id=uuid.uuid4(),
            request_id=request.request_id,
            set_id=artifact_set.set_id,
            set_version=artifact_set.set_version,
            required_formats=artifact_set.required_formats,
            mappings=mappings,
            accessibility_receipts=access_receipts,
            is_accessible=True,
            review_route=review_route,
            created_at=datetime.now(timezone.utc),
        )
        self.engine.artifact_deliveries.commit_delivery_set_receipt(set_receipt)
        return set_receipt, None

    def reopen_delivery(
        self,
        request_id: uuid.UUID,
    ) -> tuple[DeliverySetReceipt | None, ClassifiedError | None]:
        """Reopen and verify an existing delivery set receipt."""
        set_receipt = self.engine.artifact_deliveries.get_delivery_set_receipt(request_id)
        if set_receipt is None:
            return None, ClassifiedError.validation(
                f"No delivery set receipt found for request {request_id}"
            )
        if not set_receipt.is_accessible:
            return None, ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                f"Delivery set for request {request_id} has not passed candidate accessibility checks",
            )
        return set_receipt, None
