"""SYNC-01 field mapping engine (SYNC-01-S02).

Produces:
- Canonical C12 SyncPayload from SyncSubmission
- Mapped Company and Job payload dictionaries for Salesforce REST upsert
- Enforces picklist mapping, null-clearing, and candidate-field exclusion
"""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.contracts.sync import SyncPayload
from job_automation.salesforce.sync_errors import SyncValidationError
from job_automation.salesforce.sync_records import SyncSubmission
from job_automation.salesforce.sync_serialization import assert_no_candidate_fields
from job_automation.salesforce.sync_settings import SyncMappingConfig


def build_sync_payload(submission: SyncSubmission) -> SyncPayload:
    """Build canonical C12 SyncPayload from a SyncSubmission."""
    return SyncPayload(
        canonical_job_id=submission.canonical_job_id,
        job_title=submission.job_title,
        company_name=submission.company_name,
        availability=submission.availability,
        assessment_disposition=submission.assessment.final_disposition,
        relevance_score=submission.assessment.relevance_score,
        score_scale=submission.assessment.score_scale,
        assessment_reasons=submission.assessment.summary_reason,
        source_urls=list(submission.source_urls),
        last_evaluated_at=submission.evaluated_at,
    )


def build_company_payload(
    submission: SyncSubmission,
    config: SyncMappingConfig,
    sequence_number: int | None = None,
    marker: str | None = None,
) -> dict[str, Any]:
    """Map canonical company data into Salesforce Company__c fields."""
    payload: dict[str, Any] = {
        config.company_name_field: submission.company_name,
    }
    if marker is not None:
        payload[config.sync_marker_field] = marker
    if sequence_number is not None:
        payload[config.sync_version_field] = sequence_number
    assert_no_candidate_fields(payload, config, context_desc="Company write")
    return payload


def build_job_payload(
    submission: SyncSubmission,
    config: SyncMappingConfig,
    sequence_number: int,
    marker: str,
    company_salesforce_id: str | None = None,
) -> dict[str, Any]:
    """Map canonical job data into Salesforce Job__c machine fields."""
    disposition_key = submission.assessment.final_disposition.value
    mapped_disposition = config.disposition_mapping.get(disposition_key, disposition_key)

    availability_key = submission.availability.value
    mapped_availability = config.availability_mapping.get(availability_key, availability_key)

    source_urls_str = (
        "\n".join(submission.source_urls) if submission.source_urls else None
    )

    payload: dict[str, Any] = {
        config.title_field: submission.job_title,
        config.availability_field: mapped_availability,
        config.disposition_field: mapped_disposition,
        config.reason_field: submission.assessment.summary_reason,
        # Explicit None allows clearing a previous score on transition from LLM to rules
        config.score_field: submission.assessment.relevance_score,
        config.score_scale_field: submission.assessment.score_scale,
        config.last_evaluated_field: submission.evaluated_at.isoformat(),
        config.source_urls_field: source_urls_str,
        config.sync_marker_field: marker,
        config.sync_version_field: sequence_number,
    }

    if company_salesforce_id is not None:
        payload[config.job_company_lookup_field] = company_salesforce_id

    assert_no_candidate_fields(payload, config, context_desc="Job write")
    return payload


def build_company_external_id(company_id: uuid.UUID) -> str:
    """Format stable external ID string for a company."""
    if not isinstance(company_id, uuid.UUID):
        raise SyncValidationError(f"Expected uuid.UUID for company_id, got {type(company_id).__name__}")
    return str(company_id)


def build_job_external_id(job_id: uuid.UUID) -> str:
    """Format stable external ID string for a job."""
    if not isinstance(job_id, uuid.UUID):
        raise SyncValidationError(f"Expected uuid.UUID for job_id, got {type(job_id).__name__}")
    return str(job_id)
