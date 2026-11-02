"""Remote state projection and reconciliation via SFCLIENT-01 (GEN-01-S05)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import (
    GetRecordRequest,
    RemoteOutcome,
    UpdateRequest,
)
from job_automation.generation.errors import ProjectionUncertainError
from job_automation.generation.ports import RequestStateProjector
from job_automation.generation.records import ProjectionIntent, ProjectionStatus
from job_automation.generation.request_mapping import RequestFieldMapping

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class SalesforceRequestStateProjector(RequestStateProjector):
    """Dispatches and reconciles durable projection intents to Salesforce Generation_Request__c."""

    def __init__(
        self,
        gateway: SalesforceGatewayV2,
        engine: StorageEngine,
        mapping: RequestFieldMapping | None = None,
    ) -> None:
        self.gateway = gateway
        self.engine = engine
        self.mapping = mapping or RequestFieldMapping()

    def project_intent(
        self,
        intent: ProjectionIntent,
    ) -> tuple[bool, ClassifiedError | None]:
        """Dispatch a persisted state projection intent to Salesforce.

        Guarantees:
        - Intent must already be persisted in SQLite before physical dispatch.
        - Network timeouts / lost responses mark the intent UNCERTAIN.
        - Success marks the intent ACKNOWLEDGED.
        """
        req_c13 = self.engine.generation_requests.get_request(intent.request_id)
        if req_c13 is None or not req_c13.salesforce_request_id:
            err = ClassifiedError.validation(f"GenerationRequest {intent.request_id} has no remote Salesforce ID")
            return False, err

        # Mark intent as sending
        intent.status = ProjectionStatus.SENDING
        intent.attempts += 1
        intent.updated_at = datetime.now(timezone.utc)
        self.engine.generation_work.update_projection_intent(intent)

        # Build update request
        update_fields: dict[str, Any] = dict(intent.payload)
        update_req = UpdateRequest(
            object_name=self.mapping.request_object,
            record_id=req_c13.salesforce_request_id,
            fields=update_fields,
        )

        res = self.gateway.update_record(update_req)
        now_utc = datetime.now(timezone.utc)

        if res.is_success and res.value is not None:
            intent.status = ProjectionStatus.ACKNOWLEDGED
            intent.acknowledged_at = now_utc
            intent.updated_at = now_utc
            self.engine.generation_work.update_projection_intent(intent)
            return True, None

        # Handle failure / uncertain transmission
        fail = res.failure
        err = fail.error if fail else ClassifiedError.transient_network("Remote update failed without failure record")
        intent.last_error = err
        intent.updated_at = now_utc

        if fail and (fail.remote_outcome == RemoteOutcome.UNKNOWN or any(a.uncertain_transmission for a in fail.attempts)):
            intent.status = ProjectionStatus.UNCERTAIN
            intent.uncertain_at = now_utc
            self.engine.generation_work.update_projection_intent(intent)
            logger.warning(
                "Projection intent %s for request %s outcome is UNCERTAIN (lost response / timeout)",
                intent.intent_id,
                intent.request_id,
            )
            return False, err

        intent.status = ProjectionStatus.FAILED
        self.engine.generation_work.update_projection_intent(intent)
        return False, err

    def reconcile_intent(
        self,
        intent: ProjectionIntent,
    ) -> tuple[bool, ClassifiedError | None]:
        """Reconcile an uncertain or unacknowledged projection intent via readback."""
        req_c13 = self.engine.generation_requests.get_request(intent.request_id)
        if req_c13 is None or not req_c13.salesforce_request_id:
            return False, ClassifiedError.validation(f"Request {intent.request_id} lacks remote ID")

        # Read back remote record
        get_req = GetRecordRequest(
            object_name=self.mapping.request_object,
            record_id=req_c13.salesforce_request_id,
            fields=[
                "Id",
                self.mapping.status_field,
                self.mapping.operation_marker_field,
            ],
        )
        res = self.gateway.get_record(get_req)
        if not res.is_success or res.value is None:
            err = res.failure.error if res.failure else ClassifiedError.transient_network("Readback failed")
            return False, err

        remote_fields = res.value.fields
        remote_marker = remote_fields.get(self.mapping.operation_marker_field)
        remote_state = remote_fields.get(self.mapping.status_field)

        now_utc = datetime.now(timezone.utc)
        if remote_marker == intent.operation_marker:
            # Operation was successfully committed remotely!
            intent.status = ProjectionStatus.ACKNOWLEDGED
            intent.acknowledged_at = now_utc
            intent.uncertain_at = None
            intent.updated_at = now_utc
            self.engine.generation_work.update_projection_intent(intent)
            logger.info("Successfully reconciled projection intent %s via remote marker match", intent.intent_id)
            return True, None

        # Check if remote record has already advanced to the desired state
        if remote_state == intent.desired_remote_state:
            intent.status = ProjectionStatus.ACKNOWLEDGED
            intent.acknowledged_at = now_utc
            intent.uncertain_at = None
            intent.updated_at = now_utc
            self.engine.generation_work.update_projection_intent(intent)
            return True, None

        # If not matched, write did not take effect. If it was uncertain, it is now safe to retry or fail.
        intent.status = ProjectionStatus.PENDING
        intent.updated_at = now_utc
        self.engine.generation_work.update_projection_intent(intent)
        return False, ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_SERVICE,
            f"Remote readback shows state '{remote_state}', expected marker '{intent.operation_marker}'",
        )
