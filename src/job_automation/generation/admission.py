"""Request admission, identity reconciliation, and preflight validation (GEN-01-S05)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.records import (
    GenerationRequestObservation,
    ObservationIssueCategory,
    ProjectionIntent,
    ProjectionStatus,
)
from job_automation.generation.request_mapping import (
    RequestFieldMapping,
    canonicalize_salesforce_id,
    derive_local_request_id,
)

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


def _parse_bool_strict(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1")
    return False


class GenerationAdmitter:
    """Admits remote observations into durable C13 GenerationRequests idempotently."""

    def __init__(
        self,
        engine: StorageEngine,
        mapping: RequestFieldMapping | None = None,
    ) -> None:
        self.engine = engine
        self.mapping = mapping or RequestFieldMapping()

    def admit_observation(
        self,
        observation: GenerationRequestObservation,
    ) -> tuple[GenerationRequest | None, ClassifiedError | None]:
        """Admit or match an observation against durable storage.

        Enforces:
        - Rejects and quarantines unmapped canonical jobs or malformed options.
        - Idempotently reuses existing C13 requests by remote ID or local UUID.
        - Flags conflicting client keys across differing remote IDs.
        - Distinct C13 identity for deliberate regenerations linked to predecessor.
        - Preflight availability failure (job_unavailable) transitions directly to Failed (never Running).
        """
        # 1. Check if observation is quarantined
        if observation.issue_category is not None:
            err = ClassifiedError.validation(
                f"Observation quarantined [{observation.issue_category.value}]: {observation.issue_message}"
            )
            return None, err

        if observation.canonical_job_id is None:
            err = ClassifiedError.validation("Cannot admit request without canonical_job_id")
            return None, err

        # 2. Check existing request by remote Salesforce ID or local UUID
        existing_req: GenerationRequest | None = None
        if observation.salesforce_request_id:
            existing_req = self.engine.generation_requests.get_by_salesforce_id(
                observation.salesforce_request_id
            )
            if existing_req is None and observation.canonical_salesforce_id:
                existing_req = self.engine.generation_requests.get_by_salesforce_id(
                    observation.canonical_salesforce_id
                )

        if existing_req is None and observation.local_request_id:
            existing_req = self.engine.generation_requests.get_request(
                observation.local_request_id
            )

        # 3. Check client request key uniqueness / conflicts
        if observation.client_request_key:
            client_req = self.engine.generation_requests.get_by_client_key(
                observation.client_request_key
            )
            if client_req is not None:
                # Detect conflicts across distinct remote records or requests
                is_conflict = False
                if existing_req is not None and client_req.request_id != existing_req.request_id:
                    is_conflict = True
                elif client_req.salesforce_request_id and observation.salesforce_request_id and (
                    client_req.salesforce_request_id != observation.salesforce_request_id
                ):
                    is_conflict = True
                elif client_req.salesforce_request_id and observation.canonical_salesforce_id and (
                    client_req.salesforce_request_id != observation.canonical_salesforce_id
                ):
                    is_conflict = True
                elif client_req.canonical_job_id != observation.canonical_job_id:
                    is_conflict = True

                if is_conflict:
                    err = ClassifiedError.validation(
                        message=(
                            f"Client key '{observation.client_request_key}' already mapped to request "
                            f"{client_req.request_id} (SF ID {client_req.salesforce_request_id}), "
                            f"conflicting with incoming request for SF ID {observation.salesforce_request_id}"
                        ),
                    )
                    return None, err
                if existing_req is None:
                    # Client key points to an existing request; reuse it
                    existing_req = client_req

        if existing_req is not None:
            # Reused active or historical request
            logger.debug("Idempotently matched existing GenerationRequest: %s", existing_req.request_id)
            return existing_req, None

        # 4. Resolve predecessor request for deliberate regenerations
        predecessor_id: uuid.UUID | None = None
        raw_pred = observation.raw_record.get(self.mapping.predecessor_field)
        if raw_pred:
            pred_str = str(raw_pred).strip()
            try:
                predecessor_id = uuid.UUID(pred_str)
            except ValueError:
                # Predecessor might be a Salesforce Record ID
                pred_c13 = self.engine.generation_requests.get_by_salesforce_id(pred_str)
                if pred_c13 is not None:
                    predecessor_id = pred_c13.request_id

        # 5. Extract options
        doc_type = DocumentType(observation.raw_record.get(self.mapping.document_type_field, "cv"))
        lang = str(observation.raw_record.get(self.mapping.target_language_field, "de"))
        template_id = str(observation.raw_record.get(self.mapping.template_id_field, "default_template"))
        strategy = ContextStrategy(observation.raw_record.get(self.mapping.context_strategy_field, "json"))
        allow_unavailable = _parse_bool_strict(
            observation.raw_record.get(self.mapping.allow_unavailable_field, False)
        )

        # Parse remote CreatedDate if present, preserving remote creation timestamp
        now_utc = datetime.now(timezone.utc)
        created_time = now_utc
        raw_created = observation.raw_record.get("CreatedDate")
        if raw_created:
            if isinstance(raw_created, datetime):
                created_time = raw_created if raw_created.tzinfo else raw_created.replace(tzinfo=timezone.utc)
            elif isinstance(raw_created, str):
                try:
                    cleaned_str = raw_created.replace("+0000", "+00:00").replace("Z", "+00:00")
                    dt_parsed = datetime.fromisoformat(cleaned_str)
                    created_time = dt_parsed if dt_parsed.tzinfo else dt_parsed.replace(tzinfo=timezone.utc)
                except ValueError:
                    created_time = now_utc

        # Assign request UUID: use local_request_id from observation, or derive UUIDv5
        req_id = observation.local_request_id or derive_local_request_id(
            observation.org_id, observation.canonical_salesforce_id
        )

        # 6. Preflight Availability Verification (R06/R10)
        job = self.engine.canonical_jobs.get_canonical_job(observation.canonical_job_id)
        if job is None:
            err = ClassifiedError.validation(f"Canonical job {observation.canonical_job_id} not found")
            return None, err

        if job.availability == PostingAvailability.UNAVAILABLE and not allow_unavailable:
            # Confirmed unavailable job without candidate override -> Immediate Preflight Failure
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="Job is unavailable and allow_unavailable_job override was not granted",
                details={"reason_code": "job_unavailable", "canonical_job_id": str(job.canonical_job_id)},
            )
            failed_req = GenerationRequest(
                request_id=req_id,
                salesforce_request_id=observation.canonical_salesforce_id,
                client_request_key=observation.client_request_key,
                canonical_job_id=observation.canonical_job_id,
                document_type=doc_type,
                target_language=lang,
                template_id=template_id,
                context_strategy=strategy,
                allow_unavailable_job=allow_unavailable,
                state=GenerationProcessing.FAILED,
                created_at=created_time,
                completed_at=now_utc,
                predecessor_request_id=predecessor_id,
                error=err,
            )
            self.engine.generation_requests.create_request(failed_req)

            # Enqueue terminal Failed projection intent (never projects Running!)
            failed_intent = ProjectionIntent(
                request_id=req_id,
                projection_revision=1,
                operation_marker=f"fail:{req_id}:{now_utc.isoformat()}",
                desired_remote_state="Failed",
                payload={
                    self.mapping.status_field: "Failed",
                    self.mapping.error_reason_field: "job_unavailable",
                },
                status=ProjectionStatus.PENDING,
                created_at=now_utc,
                updated_at=now_utc,
            )
            self.engine.generation_work.save_projection_intent(failed_intent)
            return failed_req, err

        # 7. Preflight passed: Admit in PENDING state
        new_req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=observation.canonical_salesforce_id,
            client_request_key=observation.client_request_key,
            canonical_job_id=observation.canonical_job_id,
            document_type=doc_type,
            target_language=lang,
            template_id=template_id,
            context_strategy=strategy,
            allow_unavailable_job=allow_unavailable,
            state=GenerationProcessing.PENDING,
            created_at=created_time,
            predecessor_request_id=predecessor_id,
        )
        self.engine.generation_requests.create_request(new_req)

        # Update observation's local_request_id
        observation.local_request_id = req_id
        self.engine.generation_work.save_observation(observation)

        return new_req, None
