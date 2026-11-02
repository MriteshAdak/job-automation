"""Serialization and query construction for Salesforce Files operations (GEN-06-S03)."""

from __future__ import annotations

import base64
import json
from typing import Any

from job_automation.contracts.errors import ClassifiedError
from job_automation.salesforce.file_records import (
    ContentDocumentLinkMetadata,
    ContentVersionMetadata,
    CreateContentDocumentLinkRequest,
    CreateContentVersionRequest,
)


def serialize_content_version_body(
    request: CreateContentVersionRequest,
    marker_field: str = "Description",
) -> bytes:
    """Serialize CreateContentVersionRequest into bounded JSON with base64 VersionData."""
    b64_data = base64.b64encode(request.version_data).decode("ascii")
    payload: dict[str, Any] = {
        "Title": request.title,
        "PathOnClient": request.path_on_client,
        "VersionData": b64_data,
        marker_field: request.reconciliation_marker,
    }
    if request.first_publish_location_id:
        payload["FirstPublishLocationId"] = request.first_publish_location_id
    if request.description and marker_field != "Description":
        payload["Description"] = request.description

    return json.dumps(payload).encode("utf-8")


def parse_create_response_id(body: bytes) -> tuple[str | None, ClassifiedError | None]:
    """Parse record ID from a 201 Created response body."""
    try:
        data = json.loads(body.decode("utf-8"))
        rec_id = data.get("id")
        if rec_id and isinstance(rec_id, str):
            return rec_id, None
        return None, ClassifiedError.validation("Create response missing 'id' field")
    except Exception as exc:
        return None, ClassifiedError.validation(f"Failed to parse create response: {exc}")


def serialize_content_document_link_body(
    request: CreateContentDocumentLinkRequest,
) -> bytes:
    """Serialize CreateContentDocumentLinkRequest into JSON body."""
    payload = {
        "ContentDocumentId": request.content_document_id,
        "LinkedEntityId": request.linked_entity_id,
        "ShareType": request.share_type,
        "Visibility": request.visibility,
    }
    return json.dumps(payload).encode("utf-8")


def build_marker_soql_query(
    marker: str,
    marker_field: str = "Description",
    limit: int = 50,
) -> str:
    """Build safe SOQL query to search ContentVersions by exact marker."""
    escaped_marker = marker.replace("'", "\\'")
    fields = [
        "Id",
        "ContentDocumentId",
        "Title",
        "VersionNumber",
        "PathOnClient",
        "ContentSize",
        "Description",
        "Checksum",
        "IsLatest",
    ]
    if marker_field not in fields:
        fields.append(marker_field)
    fields_clause = ", ".join(fields)
    return (
        f"SELECT {fields_clause} FROM ContentVersion "
        f"WHERE {marker_field} = '{escaped_marker}' "
        f"ORDER BY CreatedDate DESC LIMIT {limit}"
    )


def build_document_links_soql_query(
    content_document_id: str,
    linked_entity_id: str | None = None,
) -> str:
    """Build safe SOQL query for ContentDocumentLinks."""
    escaped_doc = content_document_id.replace("'", "\\'")
    query = (
        "SELECT Id, ContentDocumentId, LinkedEntityId, ShareType, Visibility "
        f"FROM ContentDocumentLink WHERE ContentDocumentId = '{escaped_doc}'"
    )
    if linked_entity_id:
        escaped_ent = linked_entity_id.replace("'", "\\'")
        query += f" AND LinkedEntityId = '{escaped_ent}'"
    return query


def parse_content_version_record(data: dict[str, Any], marker_field: str = "Description") -> ContentVersionMetadata:
    """Parse JSON dictionary into ContentVersionMetadata."""
    return ContentVersionMetadata(
        content_version_id=data["Id"],
        content_document_id=data["ContentDocumentId"],
        title=data.get("Title", ""),
        version_number=str(data.get("VersionNumber", "1")),
        path_on_client=data.get("PathOnClient"),
        content_size=int(data.get("ContentSize", 0)),
        reconciliation_marker=data.get(marker_field) or data.get("Description"),
        description=data.get("Description"),
        checksum=data.get("Checksum"),
        is_latest=bool(data.get("IsLatest", True)),
    )


def parse_content_document_link_record(data: dict[str, Any]) -> ContentDocumentLinkMetadata:
    """Parse JSON dictionary into ContentDocumentLinkMetadata."""
    return ContentDocumentLinkMetadata(
        link_id=data["Id"],
        content_document_id=data["ContentDocumentId"],
        linked_entity_id=data["LinkedEntityId"],
        share_type=data.get("ShareType", "V"),
        visibility=data.get("Visibility", "AllUsers"),
    )

