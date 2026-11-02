"""Port protocols for artifact delivery and Salesforce Files gateway (GEN-06-S01)."""

from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.salesforce import GatewayResult
from job_automation.generation.delivery_records import (
    AccessibilityReceipt,
    DeliverySetReceipt,
    RemoteArtifactMapping,
)
from job_automation.generation.render_records import ArtifactSet
from job_automation.salesforce.file_records import (
    ContentDocumentLinkMetadata,
    ContentVersionMetadata,
    CreateContentDocumentLinkRequest,
    CreateContentDocumentLinkResult,
    CreateContentVersionRequest,
    CreateContentVersionResult,
)


@runtime_checkable
class SalesforceFilesGatewayPort(Protocol):
    """Narrow typed operations for Salesforce Files (ContentVersion and ContentDocumentLink)."""

    def create_content_version(
        self,
        request: CreateContentVersionRequest,
    ) -> GatewayResult[CreateContentVersionResult]:
        """Upload raw file bytes and marker to create a new ContentVersion."""
        ...

    def get_content_version(
        self,
        version_id: str,
    ) -> GatewayResult[ContentVersionMetadata]:
        """Retrieve metadata for a specific ContentVersion by ID."""
        ...

    def query_content_versions_by_marker(
        self,
        marker: str,
    ) -> GatewayResult[list[ContentVersionMetadata]]:
        """Query ContentVersions across the org by exact reconciliation marker."""
        ...

    def create_content_document_link(
        self,
        request: CreateContentDocumentLinkRequest,
    ) -> GatewayResult[CreateContentDocumentLinkResult]:
        """Link a ContentDocument to a Salesforce record (e.g. Generation_Request__c)."""
        ...

    def query_content_document_links(
        self,
        content_document_id: str,
        linked_entity_id: str | None = None,
    ) -> GatewayResult[list[ContentDocumentLinkMetadata]]:
        """Query links for a ContentDocument, optionally filtered by linked entity."""
        ...

    def download_content_version_bytes(
        self,
        version_id: str,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> GatewayResult[bytes]:
        """Download exact version bytes for integrity and checksum verification."""
        ...


@runtime_checkable
class ArtifactDeliveryServicePort(Protocol):
    """Delivery coordinator protocol for sealing artifact sets and reconciling uploads."""

    def deliver_or_reconcile(
        self,
        request: GenerationRequest,
        artifact_set: ArtifactSet,
        salesforce_request_id: str,
        canonical_salesforce_id: str,
    ) -> tuple[DeliverySetReceipt | None, ClassifiedError | None]:
        """Deliver all required formats of an ArtifactSet to Salesforce Files or reconcile existing uploads."""
        ...

    def reopen_delivery(
        self,
        request_id: uuid.UUID,
    ) -> tuple[DeliverySetReceipt | None, ClassifiedError | None]:
        """Reopen and verify an existing delivery set receipt."""
        ...

