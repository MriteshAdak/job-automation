"""Candidate file accessibility verification and proof receipts (GEN-06-S05)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.delivery_ports import SalesforceFilesGatewayPort
from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    RemoteArtifactMapping,
)
from job_automation.generation.input_records import compute_sha256_digest

logger = logging.getLogger(__name__)


def verify_candidate_access(
    gateway: SalesforceFilesGatewayPort,
    mapping: RemoteArtifactMapping,
    verification_method: Literal[
        "direct_download", "sharing_policy_check", "mock_verification"
    ] = "sharing_policy_check",
    candidate_principal: str | None = None,
) -> tuple[AccessibilityReceipt | None, ClassifiedError | None]:
    """Verify that a remotely uploaded file is candidate-accessible and produce proof receipt."""
    if not mapping.content_version_id or not mapping.content_document_id:
        return None, ClassifiedError.validation("Cannot verify access: missing remote file IDs")

    if not mapping.link_id:
        return None, ClassifiedError.validation("Cannot verify access: file is not linked to target record")

    now_utc = datetime.now(timezone.utc)

    # Strategy 1: Sharing policy check
    if verification_method == "sharing_policy_check":
        links_res = gateway.query_content_document_links(
            content_document_id=mapping.content_document_id,
            linked_entity_id=mapping.target_record_id,
        )
        if links_res.is_failure or not links_res.value:
            return None, ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                f"Candidate access unverified: ContentDocumentLink missing for entity {mapping.target_record_id}",
            )
        link = links_res.value[0]
        if link.share_type not in ("V", "C", "I"):
            return None, ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                f"Candidate access unverified: share type '{link.share_type}' insufficient",
            )

    # Strategy 2: Direct download and byte integrity check
    elif verification_method == "direct_download":
        dl_res = gateway.download_content_version_bytes(mapping.content_version_id)
        if dl_res.is_failure or dl_res.value is None:
            return None, ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                f"Candidate access check failed: could not download version bytes for {mapping.content_version_id}",
            )
        hash_check = "sha256:" + compute_sha256_digest(dl_res.value).split(":")[-1]
        if hash_check != mapping.content_hash:
            return None, ClassifiedError.validation(
                f"Candidate access integrity failure: downloaded bytes hash '{hash_check}' != expected '{mapping.content_hash}'"
            )

    # Strategy 3: Mock verification (for offline unit tests)
    elif verification_method == "mock_verification":
        pass

    receipt = AccessibilityReceipt(
        receipt_id=uuid.uuid4(),
        mapping_id=mapping.mapping_id,
        request_id=mapping.request_id,
        artifact_id=mapping.artifact_id,
        artifact_version=mapping.artifact_version,
        artifact_format=mapping.artifact_format,
        content_version_id=mapping.content_version_id,
        content_document_id=mapping.content_document_id,
        target_record_id=mapping.target_record_id,
        verification_method=verification_method,
        candidate_principal=candidate_principal,
        verified_at=now_utc,
    )
    return receipt, None

