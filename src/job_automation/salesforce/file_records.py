"""Salesforce Files API contract records and typed operation models (SFCLIENT-01 Files extension).

Defines:
- ContentVersion creation, reading, and querying records.
- ContentDocumentLink creation and querying records.
- Exact byte download parameters and integrity checks.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.primitives import UtcDatetime


class CreateContentVersionRequest(ContractModel):
    """Request to create a single ContentVersion with attached file bytes and marker."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    title: str = Field(min_length=1, max_length=255)
    path_on_client: str = Field(
        min_length=1,
        max_length=255,
        description="Safe file name with extension; never a full Windows path",
    )
    version_data: bytes = Field(description="Raw file bytes to be base64-encoded on wire")
    reconciliation_marker: str = Field(min_length=1, max_length=255)
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    first_publish_location_id: str | None = Field(
        default=None,
        min_length=15,
        max_length=18,
        description="Optional record ID to immediately link ContentVersion on creation",
    )
    description: str | None = None

    @field_validator("path_on_client")
    @classmethod
    def validate_safe_filename(cls, v: str) -> str:
        # Forbid backslashes or slashes to prevent exposing Windows directory structure
        if "/" in v or "\\" in v:
            raise ValueError(f"path_on_client must be a bare filename, not a path: {v}")
        return v


class CreateContentVersionResult(ContractModel):
    """Result of creating a ContentVersion."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    content_version_id: str = Field(min_length=15, max_length=18)
    content_document_id: str = Field(min_length=15, max_length=18)
    reconciliation_marker: str | None = None


class ContentVersionMetadata(ContractModel):
    """Readback metadata for a Salesforce ContentVersion."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    content_version_id: str = Field(min_length=15, max_length=18)
    content_document_id: str = Field(min_length=15, max_length=18)
    title: str
    version_number: str = "1"
    path_on_client: str | None = None
    content_size: int = Field(ge=0)
    reconciliation_marker: str | None = None
    description: str | None = None
    checksum: str | None = None
    is_latest: bool = True


class CreateContentDocumentLinkRequest(ContractModel):
    """Request to create a ContentDocumentLink relationship."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    content_document_id: str = Field(min_length=15, max_length=18)
    linked_entity_id: str = Field(min_length=15, max_length=18)
    share_type: Literal["V", "C", "I"] = Field(
        default="V", description="V = Viewer, C = Collaborator, I = Inferred"
    )
    visibility: Literal["AllUsers", "InternalUsers", "SharedUsers"] = Field(
        default="AllUsers", description="Visibility of file on record"
    )


class CreateContentDocumentLinkResult(ContractModel):
    """Result of creating a ContentDocumentLink."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    link_id: str = Field(min_length=15, max_length=18)
    content_document_id: str = Field(min_length=15, max_length=18)
    linked_entity_id: str = Field(min_length=15, max_length=18)
    share_type: str = "V"
    visibility: str = "AllUsers"


class ContentDocumentLinkMetadata(ContractModel):
    """Metadata for an existing ContentDocumentLink."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    link_id: str = Field(min_length=15, max_length=18)
    content_document_id: str = Field(min_length=15, max_length=18)
    linked_entity_id: str = Field(min_length=15, max_length=18)
    share_type: str
    visibility: str


from typing import Protocol, runtime_checkable
from job_automation.contracts.salesforce import GatewayResult


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

