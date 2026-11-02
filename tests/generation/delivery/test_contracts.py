"""Tests for GEN-06 delivery contracts, value objects, and marker grammar (GEN-06-S01)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliveryAttempt,
    DeliveryIntent,
    DeliverySetReceipt,
    RemoteArtifactMapping,
    ReviewProjection,
    ReadinessTransitionRecord,
    build_reconciliation_marker,
    parse_reconciliation_marker,
)
from job_automation.generation.delivery_settings import DeliverySettings
from job_automation.salesforce.file_records import (
    ContentDocumentLinkMetadata,
    ContentVersionMetadata,
    CreateContentDocumentLinkRequest,
    CreateContentDocumentLinkResult,
    CreateContentVersionRequest,
    CreateContentVersionResult,
)


def test_reconciliation_marker_grammar_roundtrip() -> None:
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    marker = build_reconciliation_marker(req_id, art_id, 1)

    assert marker == f"gen06:v1:{req_id}:{art_id}:1"
    parsed_req, parsed_art, parsed_ver = parse_reconciliation_marker(marker)
    assert parsed_req == req_id
    assert parsed_art == art_id
    assert parsed_ver == 1


def test_reconciliation_marker_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid reconciliation marker"):
        parse_reconciliation_marker("invalid_marker")

    with pytest.raises(ValueError, match="artifact_version must be >= 1"):
        build_reconciliation_marker(uuid.uuid4(), uuid.uuid4(), 0)


def test_delivery_intent_validation() -> None:
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    marker = build_reconciliation_marker(req_id, art_id, 1)

    intent = DeliveryIntent(
        intent_id=uuid.uuid4(),
        org_id="00D000000000001EAA",
        salesforce_request_id="a01000000000001AAA",
        canonical_salesforce_id="a00000000000001AAA",
        request_id=req_id,
        artifact_set_id=uuid.uuid4(),
        artifact_id=art_id,
        artifact_version=1,
        artifact_format="docx",
        content_hash="sha256:" + "a" * 64,
        size_bytes=1024,
        local_path="C:/Data/file.docx",
        reconciliation_marker=marker,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    assert intent.logical_key == f"00D000000000001EAA:{req_id}:{art_id}:1"

    # Invalid marker grammar rejects
    with pytest.raises(ValidationError):
        DeliveryIntent(
            intent_id=uuid.uuid4(),
            org_id="00D000000000001EAA",
            salesforce_request_id="a01000000000001AAA",
            canonical_salesforce_id="a00000000000001AAA",
            request_id=req_id,
            artifact_set_id=uuid.uuid4(),
            artifact_id=art_id,
            artifact_version=1,
            artifact_format="docx",
            content_hash="sha256:" + "a" * 64,
            size_bytes=1024,
            local_path="C:/Data/file.docx",
            reconciliation_marker="bad_marker",
            status="pending",
            created_at=now,
            updated_at=now,
        )

    # Zero byte size rejects
    with pytest.raises(ValidationError):
        DeliveryIntent(
            intent_id=uuid.uuid4(),
            org_id="00D000000000001EAA",
            salesforce_request_id="a01000000000001AAA",
            canonical_salesforce_id="a00000000000001AAA",
            request_id=req_id,
            artifact_set_id=uuid.uuid4(),
            artifact_id=art_id,
            artifact_version=1,
            artifact_format="docx",
            content_hash="sha256:" + "a" * 64,
            size_bytes=0,
            local_path="C:/Data/file.docx",
            reconciliation_marker=marker,
            status="pending",
            created_at=now,
            updated_at=now,
        )


def test_create_content_version_request_forbids_windows_path_in_path_on_client() -> None:
    # Backslash or slash in path_on_client is rejected to prevent leaking directory structure
    with pytest.raises(ValidationError, match="path_on_client must be a bare filename"):
        CreateContentVersionRequest(
            title="CV",
            path_on_client="C:\\Users\\mrite\\file.docx",
            version_data=b"dummy",
            reconciliation_marker="gen06:v1:test",
            content_hash="sha256:" + "a" * 64,
        )

    # Safe bare filename passes
    req = CreateContentVersionRequest(
        title="CV",
        path_on_client="document.docx",
        version_data=b"dummy",
        reconciliation_marker="gen06:v1:test",
        content_hash="sha256:" + "a" * 64,
    )
    assert req.path_on_client == "document.docx"


def test_delivery_set_receipt_accessibility_check() -> None:
    req_id = uuid.uuid4()
    art_docx_id = uuid.uuid4()
    art_pdf_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    docx_mapping = RemoteArtifactMapping(
        mapping_id=uuid.uuid4(),
        intent_id=uuid.uuid4(),
        request_id=req_id,
        artifact_id=art_docx_id,
        artifact_version=1,
        artifact_format="docx",
        content_hash="sha256:" + "1" * 64,
        org_id="00D000000000001EAA",
        content_document_id="069000000000001AAA",
        content_version_id="068000000000001AAA",
        marker=build_reconciliation_marker(req_id, art_docx_id, 1),
        target_record_id="a01000000000001AAA",
        link_id="06A000000000001AAA",
        acknowledged_at=now,
    )

    docx_access = AccessibilityReceipt(
        receipt_id=uuid.uuid4(),
        mapping_id=docx_mapping.mapping_id,
        request_id=req_id,
        artifact_id=art_docx_id,
        artifact_version=1,
        artifact_format="docx",
        content_version_id="068000000000001AAA",
        content_document_id="069000000000001AAA",
        target_record_id="a01000000000001AAA",
        verification_method="sharing_policy_check",
        verified_at=now,
    )

    # Partial set: PDF is required but missing -> is_accessible is False!
    partial_receipt = DeliverySetReceipt(
        set_receipt_id=uuid.uuid4(),
        request_id=req_id,
        set_id=uuid.uuid4(),
        set_version=1,
        required_formats=["docx", "pdf"],
        mappings={"docx": docx_mapping},
        accessibility_receipts={"docx": docx_access},
        review_route="https://test.salesforce.com/view",
        created_at=now,
    )
    assert partial_receipt.is_accessible is False

    # Full set with PDF mapped and verified accessible -> is_accessible is True!
    pdf_mapping = docx_mapping.model_copy(
        update={
            "mapping_id": uuid.uuid4(),
            "artifact_id": art_pdf_id,
            "artifact_format": "pdf",
            "content_version_id": "068000000000002AAA",
            "content_document_id": "069000000000002AAA",
            "marker": build_reconciliation_marker(req_id, art_pdf_id, 1),
        }
    )
    pdf_access = docx_access.model_copy(
        update={
            "receipt_id": uuid.uuid4(),
            "artifact_id": art_pdf_id,
            "artifact_format": "pdf",
            "content_version_id": "068000000000002AAA",
            "content_document_id": "069000000000002AAA",
        }
    )

    full_receipt = DeliverySetReceipt(
        set_receipt_id=uuid.uuid4(),
        request_id=req_id,
        set_id=uuid.uuid4(),
        set_version=1,
        required_formats=["docx", "pdf"],
        mappings={"docx": docx_mapping, "pdf": pdf_mapping},
        accessibility_receipts={"docx": docx_access, "pdf": pdf_access},
        review_route="https://test.salesforce.com/view",
        created_at=now,
    )
    assert full_receipt.is_accessible is True
    assert full_receipt.receipt_hash.startswith("sha256:")
