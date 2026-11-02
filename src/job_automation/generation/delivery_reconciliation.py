"""Upload and link reconciliation for ambiguous delivery outcomes (GEN-06-S04)."""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.delivery_ports import SalesforceFilesGatewayPort
from job_automation.generation.delivery_records import DeliveryIntent
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.salesforce.file_records import (
    ContentDocumentLinkMetadata,
    ContentVersionMetadata,
    CreateContentDocumentLinkRequest,
)

logger = logging.getLogger(__name__)


class ReconciliationOutcome(StrEnum):
    """Categorized outcome of reconciling an upload by reconciliation marker."""

    EXACT_MATCH = "exact_match"
    PROVEN_ABSENT = "proven_absent"
    INCONCLUSIVE = "inconclusive"
    CONFLICT = "conflict"


class ReconciliationResult:
    """Result envelope for upload marker reconciliation."""

    def __init__(
        self,
        outcome: ReconciliationOutcome,
        content_version_id: str | None = None,
        content_document_id: str | None = None,
        reason: str | None = None,
        records: list[ContentVersionMetadata] | None = None,
    ) -> None:
        self.outcome = outcome
        self.content_version_id = content_version_id
        self.content_document_id = content_document_id
        self.reason = reason
        self.records = records or []


def reconcile_upload_by_marker(
    gateway: SalesforceFilesGatewayPort,
    intent: DeliveryIntent,
    verify_content_bytes: bool = False,
) -> ReconciliationResult:
    """Reconcile an upload intent by querying Salesforce for its unique marker."""
    query_res = gateway.query_content_versions_by_marker(intent.reconciliation_marker)
    if query_res.is_failure:
        fail = query_res.failure
        msg = fail.error.message if fail else "Marker query failed"
        return ReconciliationResult(
            outcome=ReconciliationOutcome.INCONCLUSIVE,
            reason=f"Failed to query marker '{intent.reconciliation_marker}': {msg}",
        )

    records = query_res.value or []

    # Case 1: Proven absent
    if len(records) == 0:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.PROVEN_ABSENT,
            reason="Zero ContentVersion records found with matching marker.",
        )

    # Case 2: Conflict (multiple matching records)
    if len(records) > 1:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.CONFLICT,
            reason=f"Multiple ContentVersion records ({len(records)}) match marker '{intent.reconciliation_marker}'",
            records=records,
        )

    # Case 3: Exactly one record found
    rec = records[0]

    # Check size if available
    if rec.content_size > 0 and rec.content_size != intent.size_bytes:
        return ReconciliationResult(
            outcome=ReconciliationOutcome.CONFLICT,
            reason=(
                f"Content size mismatch: remote has {rec.content_size} bytes, "
                f"expected {intent.size_bytes} bytes"
            ),
            records=records,
        )

    # If byte verification requested, download and check SHA-256
    if verify_content_bytes:
        dl_res = gateway.download_content_version_bytes(
            rec.content_version_id, max_bytes=intent.size_bytes + 1024
        )
        if dl_res.is_failure:
            return ReconciliationResult(
                outcome=ReconciliationOutcome.INCONCLUSIVE,
                reason="Failed to download version bytes for verification",
                records=records,
            )
        raw_bytes = dl_res.value or b""
        actual_hash = "sha256:" + compute_sha256_digest(raw_bytes).split(":")[-1]
        if actual_hash != intent.content_hash:
            return ReconciliationResult(
                outcome=ReconciliationOutcome.CONFLICT,
                reason=f"Content hash mismatch: remote bytes hash '{actual_hash}', expected '{intent.content_hash}'",
                records=records,
            )

    return ReconciliationResult(
        outcome=ReconciliationOutcome.EXACT_MATCH,
        content_version_id=rec.content_version_id,
        content_document_id=rec.content_document_id,
        records=records,
    )


def reconcile_or_create_link(
    gateway: SalesforceFilesGatewayPort,
    content_document_id: str,
    target_record_id: str,
    share_type: str = "V",
    visibility: str = "AllUsers",
) -> tuple[str | None, ClassifiedError | None]:
    """Reconcile an existing ContentDocumentLink or create it if absent."""
    # 1. Query existing links
    q_res = gateway.query_content_document_links(
        content_document_id=content_document_id,
        linked_entity_id=target_record_id,
    )
    if q_res.is_success and q_res.value:
        matching_link = q_res.value[0]
        return matching_link.link_id, None

    # 2. Link not found; create link
    create_req = CreateContentDocumentLinkRequest(
        content_document_id=content_document_id,
        linked_entity_id=target_record_id,
        share_type=share_type,  # type: ignore[arg-type]
        visibility=visibility,  # type: ignore[arg-type]
    )
    c_res = gateway.create_content_document_link(create_req)
    if c_res.is_success and c_res.value:
        return c_res.value.link_id, None

    err = (
        c_res.failure.error
        if c_res.failure
        else ClassifiedError.transient_network("Failed to link ContentDocument to target record")
    )
    return None, err

