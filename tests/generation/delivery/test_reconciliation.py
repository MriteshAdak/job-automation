"""Tests for upload reconciliation and link reconciliation (GEN-06-S04)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.salesforce import GatewayResult
from job_automation.generation.delivery_reconciliation import (
    ReconciliationOutcome,
    reconcile_or_create_link,
    reconcile_upload_by_marker,
)
from job_automation.generation.delivery_records import (
    DeliveryIntent,
    build_reconciliation_marker,
)
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.salesforce.file_records import (
    ContentDocumentLinkMetadata,
    ContentVersionMetadata,
    CreateContentDocumentLinkRequest,
    CreateContentDocumentLinkResult,
    CreateContentVersionRequest,
    CreateContentVersionResult,
)


class MockFilesGateway:
    """Mock files gateway implementing SalesforceFilesGatewayPort."""

    def __init__(self) -> None:
        self.versions_by_marker: dict[str, list[ContentVersionMetadata]] = {}
        self.links: list[ContentDocumentLinkMetadata] = []
        self.create_link_calls: list[CreateContentDocumentLinkRequest] = []
        self.fail_query: bool = False
        self.downloaded_bytes: dict[str, bytes] = {}

    def query_content_versions_by_marker(self, marker: str) -> GatewayResult[list[ContentVersionMetadata]]:
        if self.fail_query:
            return GatewayResult.fail(
                GatewayResult.fail(
                    ClassifiedError.transient_network("Query timeout"),
                ).failure  # type: ignore[arg-type]
            )
        recs = self.versions_by_marker.get(marker, [])
        return GatewayResult.success(recs)

    def download_content_version_bytes(self, version_id: str, max_bytes: int = 10485760) -> GatewayResult[bytes]:
        data = self.downloaded_bytes.get(version_id, b"default")
        return GatewayResult.success(data)

    def query_content_document_links(
        self, content_document_id: str, linked_entity_id: str | None = None
    ) -> GatewayResult[list[ContentDocumentLinkMetadata]]:
        matched = [
            link
            for link in self.links
            if link.content_document_id == content_document_id
            and (linked_entity_id is None or link.linked_entity_id == linked_entity_id)
        ]
        return GatewayResult.success(matched)

    def create_content_document_link(
        self, request: CreateContentDocumentLinkRequest
    ) -> GatewayResult[CreateContentDocumentLinkResult]:
        self.create_link_calls.append(request)
        link = ContentDocumentLinkMetadata(
            link_id="06A000000000001AAA",
            content_document_id=request.content_document_id,
            linked_entity_id=request.linked_entity_id,
            share_type=request.share_type,
            visibility=request.visibility,
        )
        self.links.append(link)
        return GatewayResult.success(
            CreateContentDocumentLinkResult(
                link_id=link.link_id,
                content_document_id=request.content_document_id,
                linked_entity_id=request.linked_entity_id,
                share_type=request.share_type,
                visibility=request.visibility,
            )
        )


def _make_intent(req_id: uuid.UUID, art_id: uuid.UUID) -> DeliveryIntent:
    now = datetime.now(timezone.utc)
    marker = build_reconciliation_marker(req_id, art_id, 1)
    return DeliveryIntent(
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
        size_bytes=100,
        local_path="C:/data/test.docx",
        reconciliation_marker=marker,
        status="uncertain",
        created_at=now,
        updated_at=now,
    )


def test_reconcile_exact_match() -> None:
    gateway = MockFilesGateway()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    intent = _make_intent(req_id, art_id)

    # Populate 1 remote version matching marker
    gateway.versions_by_marker[intent.reconciliation_marker] = [
        ContentVersionMetadata(
            content_version_id="068000000000001AAA",
            content_document_id="069000000000001AAA",
            title="CV_DOCX",
            content_size=100,
            reconciliation_marker=intent.reconciliation_marker,
        )
    ]

    res = reconcile_upload_by_marker(gateway, intent)
    assert res.outcome == ReconciliationOutcome.EXACT_MATCH
    assert res.content_version_id == "068000000000001AAA"
    assert res.content_document_id == "069000000000001AAA"


def test_reconcile_proven_absent() -> None:
    gateway = MockFilesGateway()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    intent = _make_intent(req_id, art_id)

    res = reconcile_upload_by_marker(gateway, intent)
    assert res.outcome == ReconciliationOutcome.PROVEN_ABSENT


def test_reconcile_conflict_on_multiple_records() -> None:
    gateway = MockFilesGateway()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()
    intent = _make_intent(req_id, art_id)

    # Two records found with same marker
    gateway.versions_by_marker[intent.reconciliation_marker] = [
        ContentVersionMetadata(
            content_version_id="068000000000001AAA",
            content_document_id="069000000000001AAA",
            title="CV_DOCX_1",
            content_size=100,
            reconciliation_marker=intent.reconciliation_marker,
        ),
        ContentVersionMetadata(
            content_version_id="068000000000002AAA",
            content_document_id="069000000000002AAA",
            title="CV_DOCX_2",
            content_size=100,
            reconciliation_marker=intent.reconciliation_marker,
        ),
    ]

    res = reconcile_upload_by_marker(gateway, intent)
    assert res.outcome == ReconciliationOutcome.CONFLICT
    assert "Multiple ContentVersion records" in (res.reason or "")


def test_reconcile_or_create_link_adopts_existing() -> None:
    gateway = MockFilesGateway()
    # Existing link
    gateway.links.append(
        ContentDocumentLinkMetadata(
            link_id="06A000000000099AAA",
            content_document_id="069000000000001AAA",
            linked_entity_id="a01000000000001AAA",
            share_type="V",
            visibility="AllUsers",
        )
    )

    link_id, err = reconcile_or_create_link(
        gateway=gateway,
        content_document_id="069000000000001AAA",
        target_record_id="a01000000000001AAA",
    )
    assert err is None
    assert link_id == "06A000000000099AAA"
    # Zero create calls performed!
    assert len(gateway.create_link_calls) == 0


def test_reconcile_or_create_link_creates_if_absent() -> None:
    gateway = MockFilesGateway()

    link_id, err = reconcile_or_create_link(
        gateway=gateway,
        content_document_id="069000000000001AAA",
        target_record_id="a01000000000001AAA",
    )
    assert err is None
    assert link_id == "06A000000000001AAA"
    assert len(gateway.create_link_calls) == 1
    assert gateway.create_link_calls[0].linked_entity_id == "a01000000000001AAA"

