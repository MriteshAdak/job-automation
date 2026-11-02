"""Review obligations, warnings, and projection payload formatting (GEN-06-S06)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.delivery_records import (
    DeliverySetReceipt,
    ReviewProjection,
)

logger = logging.getLogger(__name__)


def build_review_projection(
    request: GenerationRequest,
    delivery_set: DeliverySetReceipt,
    warnings: list[str] | None = None,
    predecessor_version_refs: dict[str, str] | None = None,
) -> ReviewProjection:
    """Build immutable ReviewProjection carrying exact version references and review obligations."""
    now_utc = datetime.now(timezone.utc)
    version_refs = {
        fmt: m.content_version_id
        for fmt, m in delivery_set.mappings.items()
    }
    doc_refs = {
        fmt: m.content_document_id
        for fmt, m in delivery_set.mappings.items()
    }

    return ReviewProjection(
        request_id=request.request_id,
        salesforce_request_id=request.salesforce_request_id or "",
        set_version=delivery_set.set_version,
        result_version_refs=version_refs,
        result_document_refs=doc_refs,
        review_warnings=warnings or [],
        predecessor_request_id=request.predecessor_request_id,
        predecessor_version_refs=predecessor_version_refs,
        delivered_at=now_utc,
    )


def format_review_payload(
    projection: ReviewProjection,
    status_field: str = "Status__c",
    error_field: str = "Error_Reason__c",
    notes_field: str = "Review_Notes__c",
    file_id_field: str = "Remote_File_Id__c",
) -> dict[str, Any]:
    """Format safe remote payload for Salesforce Generation_Request__c Ready_for_Review projection."""
    payload: dict[str, Any] = {
        status_field: "Ready_for_Review",
    }
    # Link primary delivered format (DOCX or PDF)
    primary_file_id = (
        projection.result_version_refs.get("docx")
        or projection.result_version_refs.get("pdf")
    )
    if primary_file_id:
        payload[file_id_field] = primary_file_id

    # Format review warnings and semantic limits notice
    review_lines = [projection.semantic_limits_notice]
    if projection.review_warnings:
        review_lines.append("Warnings for reviewer:")
        for w in projection.review_warnings:
            review_lines.append(f"- {w}")

    if projection.predecessor_request_id:
        review_lines.append(f"Deliberate regeneration of predecessor request: {projection.predecessor_request_id}")

    payload[notes_field] = "\n".join(review_lines)
    return payload

