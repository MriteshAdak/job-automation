"""Salesforce request polling and observation mapping (GEN-01-S04)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import (
    GetRecordRequest,
    QueryPageRequest,
    validate_salesforce_identifier,
)
from job_automation.generation.ports import GenerationRequestSource
from job_automation.generation.records import (
    GenerationRequestObservation,
    ObservationIssueCategory,
    RemoteRequestState,
)
from job_automation.generation.request_mapping import (
    RequestFieldMapping,
    canonicalize_salesforce_id,
    compute_options_digest,
    derive_local_request_id,
)

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class SalesforceGenerationRequestSource(GenerationRequestSource):
    """Discovers outbound generation requests from Salesforce via SFCLIENT-01."""

    def __init__(
        self,
        gateway: SalesforceGatewayV2,
        mapping: RequestFieldMapping | None = None,
        org_id: str | None = None,
        engine: StorageEngine | None = None,
    ) -> None:
        self.gateway = gateway
        self.mapping = mapping or RequestFieldMapping()
        self.org_id = org_id or self.mapping.expected_org_id
        self.engine = engine

        # Validate identifiers on startup to prevent SOQL injection
        self._validate_identifiers()

    def _validate_identifiers(self) -> None:
        self.mapping.validate_identifiers()

    def _get_select_fields(self) -> list[str]:
        return [
            "Id",
            "CreatedDate",
            "SystemModstamp",
            self.mapping.job_lookup_field,
            self.mapping.document_type_field,
            self.mapping.target_language_field,
            self.mapping.template_id_field,
            self.mapping.context_strategy_field,
            self.mapping.allow_unavailable_field,
            self.mapping.status_field,
            self.mapping.worker_claimed_at_field,
            self.mapping.operation_marker_field,
            self.mapping.predecessor_field,
            self.mapping.client_key_field,
            self.mapping.error_reason_field,
        ]

    def _build_soql(self, lane: str, limit: int) -> str:
        fields = ", ".join(self._get_select_fields())
        status_field = self.mapping.status_field
        obj = self.mapping.request_object

        if lane == "pending":
            return (
                f"SELECT {fields} FROM {obj} "
                f"WHERE {status_field} = 'Pending' "
                f"ORDER BY CreatedDate ASC LIMIT {limit}"
            )
        elif lane == "running":
            claimed_field = self.mapping.worker_claimed_at_field
            return (
                f"SELECT {fields} FROM {obj} "
                f"WHERE {status_field} = 'Running' "
                f"ORDER BY {claimed_field} ASC LIMIT {limit}"
            )
        elif lane == "upload_pending":
            return (
                f"SELECT {fields} FROM {obj} "
                f"WHERE {status_field} = 'Upload_Pending' "
                f"ORDER BY CreatedDate ASC LIMIT {limit}"
            )
        else:
            return (
                f"SELECT {fields} FROM {obj} "
                f"ORDER BY CreatedDate ASC LIMIT {limit}"
            )

    def poll_requests(
        self,
        lane: str,
        continuation_token: str | None = None,
        limit: int = 20,
    ) -> tuple[list[GenerationRequestObservation], str | None, ClassifiedError | None]:
        """Fetch a page of remote generation request observations with cursor continuation."""
        if continuation_token:
            req = QueryPageRequest(continuation_token=continuation_token)
        else:
            soql = self._build_soql(lane, limit)
            req = QueryPageRequest(soql=soql)

        res = self.gateway.query_page(req)
        if not res.is_success or res.value is None:
            err = res.failure.error if res.failure else ClassifiedError.transient_network("Query page failed")
            return [], None, err

        page = res.value
        observations: list[GenerationRequestObservation] = []
        for raw in page.records:
            obs = self._record_to_observation(raw)
            if self.engine is not None:
                self.engine.generation_work.save_observation(obs)
            observations.append(obs)

        next_token = page.next_records_url if not page.done else None
        return observations, next_token, None

    def get_request(
        self, salesforce_request_id: str
    ) -> tuple[GenerationRequestObservation | None, ClassifiedError | None]:
        """Fetch a single record by Salesforce Record ID."""
        try:
            canonical_id = canonicalize_salesforce_id(salesforce_request_id)
        except ValueError as exc:
            return None, ClassifiedError.validation(f"Invalid record ID: {exc}")

        req = GetRecordRequest(
            object_name=self.mapping.request_object,
            record_id=canonical_id,
            fields=self._get_select_fields(),
        )
        res = self.gateway.get_record(req)
        if not res.is_success or res.value is None:
            err = res.failure.error if res.failure else ClassifiedError.not_found("Record not found")
            return None, err

        obs = self._record_to_observation(res.value.fields)
        if self.engine is not None:
            self.engine.generation_work.save_observation(obs)
        return obs, None

    def _record_to_observation(self, raw: dict[str, Any]) -> GenerationRequestObservation:
        sf_id = str(raw.get("Id", "")).strip()
        try:
            canonical_sf_id = canonicalize_salesforce_id(sf_id)
        except Exception:
            canonical_sf_id = sf_id

        # Timestamps
        observed_at = datetime.now(timezone.utc)
        modstamp_str = raw.get("SystemModstamp") or raw.get("CreatedDate")
        remote_updated_at: datetime | None = None
        if modstamp_str:
            try:
                remote_updated_at = datetime.fromisoformat(modstamp_str)
            except Exception:
                pass

        # Remote state
        raw_state = raw.get(self.mapping.status_field, "Pending")
        remote_state = str(raw_state)

        # Client key & Predecessor
        client_key = raw.get(self.mapping.client_key_field)
        client_key_str = str(client_key).strip() if client_key else None

        # Resolve local UUID
        local_request_id = derive_local_request_id(self.org_id, canonical_sf_id)

        # Extract options and validate
        job_val = raw.get(self.mapping.job_lookup_field)
        doc_type_val = raw.get(self.mapping.document_type_field, "cv")
        lang_val = raw.get(self.mapping.target_language_field, "de")
        template_val = raw.get(self.mapping.template_id_field, "default_template")
        strategy_val = raw.get(self.mapping.context_strategy_field, "json")
        allow_unavail_val = bool(raw.get(self.mapping.allow_unavailable_field, False))

        issue_cat: ObservationIssueCategory | None = None
        issue_msg: str | None = None
        canonical_job_id: uuid.UUID | None = None

        # Validate job reference
        if not job_val:
            issue_cat = ObservationIssueCategory.UNMAPPED_JOB
            issue_msg = f"Missing required job lookup field '{self.mapping.job_lookup_field}'"
        else:
            # Check if job_val is UUID
            try:
                candidate_job_uuid = uuid.UUID(str(job_val))
                if self.engine is not None:
                    job = self.engine.canonical_jobs.get_canonical_job(candidate_job_uuid)
                    if job is None:
                        issue_cat = ObservationIssueCategory.UNMAPPED_JOB
                        issue_msg = f"Canonical job '{candidate_job_uuid}' not found in database"
                    else:
                        canonical_job_id = candidate_job_uuid
                else:
                    canonical_job_id = candidate_job_uuid
            except ValueError:
                # Might be external ID or Salesforce ID
                issue_cat = ObservationIssueCategory.UNMAPPED_JOB
                issue_msg = f"Non-UUID canonical job ID '{job_val}' could not be resolved"

        # Validate document type
        try:
            DocumentType(doc_type_val)
        except ValueError:
            issue_cat = ObservationIssueCategory.INVALID_OPTIONS
            issue_msg = f"Invalid document_type '{doc_type_val}'; must be 'cv' or 'cover_letter'"

        # Validate context strategy
        try:
            ContextStrategy(strategy_val)
        except ValueError:
            issue_cat = ObservationIssueCategory.INVALID_OPTIONS
            issue_msg = f"Invalid context_strategy '{strategy_val}'; must be 'json' or 'rag'"

        # Compute digest
        options_dict = {
            "canonical_job_id": str(canonical_job_id) if canonical_job_id else str(job_val),
            "document_type": doc_type_val,
            "target_language": lang_val,
            "template_id": template_val,
            "context_strategy": strategy_val,
            "allow_unavailable_job": allow_unavail_val,
        }
        digest = compute_options_digest(options_dict)

        return GenerationRequestObservation(
            org_id=self.org_id,
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canonical_sf_id,
            client_request_key=client_key_str,
            local_request_id=local_request_id,
            canonical_job_id=canonical_job_id,
            remote_state=remote_state,
            observed_options_digest=digest,
            observed_at=observed_at,
            remote_updated_at=remote_updated_at,
            issue_category=issue_cat,
            issue_message=issue_msg,
            raw_record=raw,
        )
