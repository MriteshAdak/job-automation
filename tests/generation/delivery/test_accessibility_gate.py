"""Tests for candidate accessibility gating (GEN-06-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.salesforce import GatewayFailure, GatewayResult, OperationKind, RemoteOutcome
from job_automation.generation.delivery_access import verify_candidate_access
from job_automation.generation.delivery_records import (
    RemoteArtifactMapping,
    build_reconciliation_marker,
)
from job_automation.salesforce.file_records import ContentDocumentLinkMetadata


class AccessMockGateway:
    """Mock gateway returning configurable ContentDocumentLinks or bytes."""

    def __init__(self) -> None:
        self.links: list[ContentDocumentLinkMetadata] = []
        self.download_bytes: bytes = b"correct_bytes"
        self.fail_download: bool = False

    def query_content_document_links(
        self, content_document_id: str, linked_entity_id: str | None = None
    ) -> GatewayResult[list[ContentDocumentLinkMetadata]]:
        return GatewayResult.success(self.links)

    def download_content_version_bytes(
        self, version_id: str, max_bytes: int = 10485760
    ) -> GatewayResult[bytes]:
        if self.fail_download:
            return GatewayResult.fail(
                GatewayFailure(
                    error=GatewayResult.fail(None).failure.error,  # type: ignore[arg-type]
                    operation_kind=OperationKind.GET_RECORD,
                    remote_outcome=RemoteOutcome.NOT_SENT,
                )
            )
        return GatewayResult.success(self.download_bytes)


def _make_mapping(req_id: uuid.UUID, art_id: uuid.UUID) -> RemoteArtifactMapping:
    now = datetime.now(timezone.utc)
    return RemoteArtifactMapping(
        mapping_id=uuid.uuid4(),
        intent_id=uuid.uuid4(),
        request_id=req_id,
        artifact_id=art_id,
        artifact_version=1,
        artifact_format="docx",
        content_hash="sha256:" + "a" * 64,
        org_id="00D000000000001EAA",
        content_document_id="069000000000001AAA",
        content_version_id="068000000000001AAA",
        marker=build_reconciliation_marker(req_id, art_id, 1),
        target_record_id="a01000000000001AAA",
        link_id="06A000000000001AAA",
        acknowledged_at=now,
    )


def test_missing_link_blocks_accessibility() -> None:
    gateway = AccessMockGateway()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    mapping = _make_mapping(req_id, art_id).model_copy(update={"link_id": None})

    receipt, err = verify_candidate_access(
        gateway=gateway,
        mapping=mapping,
        verification_method="sharing_policy_check",
    )
    assert receipt is None
    assert err is not None
    assert "file is not linked to target record" in err.message


def test_insufficient_sharing_policy_blocks_accessibility() -> None:
    gateway = AccessMockGateway()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    mapping = _make_mapping(req_id, art_id)

    # Empty links returned by gateway
    gateway.links = []
    receipt, err = verify_candidate_access(
        gateway=gateway,
        mapping=mapping,
        verification_method="sharing_policy_check",
    )
    assert receipt is None
    assert err is not None
    assert err.category == ErrorCategory.PERMISSION
    assert "ContentDocumentLink missing" in err.message


def test_successful_sharing_policy_check() -> None:
    gateway = AccessMockGateway()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    mapping = _make_mapping(req_id, art_id)

    # Valid link present
    gateway.links = [
        ContentDocumentLinkMetadata(
            link_id="06A000000000001AAA",
            content_document_id=mapping.content_document_id,
            linked_entity_id=mapping.target_record_id,
            share_type="V",
            visibility="AllUsers",
        )
    ]
    receipt, err = verify_candidate_access(
        gateway=gateway,
        mapping=mapping,
        verification_method="sharing_policy_check",
        candidate_principal="candidate@example.com",
    )
    assert err is None
    assert receipt is not None
    assert receipt.candidate_principal == "candidate@example.com"
    assert receipt.receipt_hash.startswith("sha256:")

