"""Recovery manager reconciling local work, remote intents, and stale Running requests (GEN-01-S07)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

from job_automation.contracts.enums import GenerationProcessing, PostingAvailability
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.ports import GenerationRequestSource, RequestStateProjector
from job_automation.generation.records import (
    GenerationRequestObservation,
    ObservationIssueCategory,
    ProjectionIntent,
    ProjectionStatus,
    RemoteRequestState,
    StageStatus,
)
from job_automation.generation.request_mapping import RequestFieldMapping
from job_automation.generation.settings import GenerationSettings

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class GenerationRecoveryManager:
    """Reconciles local checkpoints, projection intents, and remote Running requests across restarts."""

    def __init__(
        self,
        engine: StorageEngine,
        projector: RequestStateProjector,
        source: GenerationRequestSource,
        settings: GenerationSettings | None = None,
        mapping: RequestFieldMapping | None = None,
    ) -> None:
        self.engine = engine
        self.projector = projector
        self.source = source
        self.settings = settings or GenerationSettings()
        self.mapping = mapping or self.settings.mapping

    def reconcile_all(self) -> list[str]:
        """Perform comprehensive recovery across local state and remote Running requests."""
        actions: list[str] = []

        # 1. Reconcile unacknowledged projection intents
        actions.extend(self._reconcile_projection_intents())

        # 2. Reconcile local unfinished requests
        actions.extend(self._reconcile_local_unfinished())

        # 3. Reconcile stale remote Running requests
        actions.extend(self._reconcile_stale_remote_running())

        return actions

    def _reconcile_projection_intents(self) -> list[str]:
        actions: list[str] = []
        unack = self.engine.generation_work.list_unacknowledged_intents()
        for intent in unack:
            logger.info("Reconciling projection intent %s for request %s (status: %s)", intent.intent_id, intent.request_id, intent.status.value)
            success, err = self.projector.reconcile_intent(intent)
            if success:
                actions.append(f"Reconciled projection intent {intent.intent_id} for request {intent.request_id}")
            elif intent.status == ProjectionStatus.PENDING:
                # Safe to retry dispatching
                p_success, p_err = self.projector.project_intent(intent)
                if p_success:
                    actions.append(f"Re-dispatched projection intent {intent.intent_id} for request {intent.request_id}")
                else:
                    actions.append(f"Projection intent {intent.intent_id} re-dispatch failed: {p_err}")
            else:
                actions.append(f"Projection intent {intent.intent_id} remains uncertain: {err}")
        return actions

    def _reconcile_local_unfinished(self) -> list[str]:
        actions: list[str] = []
        unfinished = self.engine.generation_requests.get_unfinished_requests()
        for req in unfinished:
            if req.state == GenerationProcessing.PENDING:
                # Still pending; awaiting freeze
                continue

            manifest = self.engine.generation_work.get_freeze_association(req.request_id)
            if manifest is None:
                # Invariant violation: request claimed without freeze manifest!
                err = ClassifiedError.validation("Request claimed without frozen manifest in storage")
                recovered = req.model_copy(
                    update={
                        "state": GenerationProcessing.FAILED,
                        "completed_at": datetime.now(timezone.utc),
                        "error": err,
                    }
                )
                self.engine.generation_requests.update_request(recovered)
                actions.append(f"Marked corrupt request {req.request_id} as FAILED (missing freeze manifest)")
                continue

            # Verify remote state
            active_intent = self.engine.generation_work.get_active_projection_intent(req.request_id)
            if active_intent and active_intent.status != ProjectionStatus.ACKNOWLEDGED:
                self.projector.reconcile_intent(active_intent)
                actions.append(f"Reconciled intent for local request {req.request_id}")

        return actions

    def _reconcile_stale_remote_running(self) -> list[str]:
        actions: list[str] = []
        if self.source is None:
            return actions
        # Query remote Running lane
        running_obs, _, err = self.source.poll_requests(lane="running", limit=self.settings.limits.max_requests_per_cycle)
        if err or not running_obs:
            return actions

        now_utc = datetime.now(timezone.utc)
        threshold = timedelta(minutes=self.settings.staleness.stale_running_minutes)
        skew = timedelta(minutes=self.settings.staleness.clock_skew_minutes)

        for obs in running_obs:
            # Check staleness timestamp
            claimed_at_val = obs.raw_record.get(self.mapping.worker_claimed_at_field)
            claimed_dt: datetime | None = None
            if claimed_at_val:
                try:
                    claimed_dt = datetime.fromisoformat(str(claimed_at_val))
                except Exception:
                    pass

            # If no timestamp, use remote_updated_at or CreatedDate
            eval_dt = claimed_dt or obs.remote_updated_at or obs.observed_at
            age = now_utc - eval_dt
            if age < (threshold - skew):
                # Request is fresh / actively held; do not steal ownership
                continue

            # Request is stale! Check local history
            local_req = self.engine.generation_requests.get_by_salesforce_id(obs.canonical_salesforce_id)
            if local_req is not None:
                manifest = self.engine.generation_work.get_freeze_association(local_req.request_id)
                if manifest is not None:
                    # Request exists locally with valid freeze association -> resume local work
                    actions.append(f"Resumed stale remote running request {local_req.request_id} from preserved freeze")
                    continue

            # Stale remote Running with no local row or missing freeze -> project actionable Failure!
            # NEVER reset to Pending and freeze current/latest inputs under the old ID!
            obs.issue_category = ObservationIssueCategory.UNMAPPED_JOB
            obs.issue_message = "Stale remote Running request with no recoverable local freeze manifest"
            self.engine.generation_work.save_observation(obs)

            fail_intent = ProjectionIntent(
                request_id=obs.local_request_id or uuid.uuid4(),
                projection_revision=1,
                operation_marker=f"stale_fail:{obs.canonical_salesforce_id}:{now_utc.isoformat()}",
                desired_remote_state="Failed",
                payload={
                    self.mapping.status_field: "Failed",
                    self.mapping.error_reason_field: "orphan_remote_running",
                },
                status=ProjectionStatus.PENDING,
                created_at=now_utc,
                updated_at=now_utc,
            )
            # Create a stub failed request record to hold the projection if needed
            stub_req = GenerationRequest(
                request_id=fail_intent.request_id,
                salesforce_request_id=obs.canonical_salesforce_id,
                canonical_job_id=obs.canonical_job_id or uuid.uuid4(),
                document_type=self._parse_doc_type(obs.raw_record.get(self.mapping.document_type_field)),
                template_id=str(obs.raw_record.get(self.mapping.template_id_field, "default")),
                state=GenerationProcessing.FAILED,
                created_at=now_utc,
                completed_at=now_utc,
                error=ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Stale remote Running request with no recoverable local freeze",
                    details={"reason_code": "orphan_remote_running"},
                ),
            )
            if self.engine.generation_requests.get_request(stub_req.request_id) is None:
                job_id = obs.canonical_job_id
                if not job_id or not self.engine.canonical_jobs.get_canonical_job(job_id):
                    target_job_id = job_id or uuid.uuid4()
                    now_ts = datetime.now(timezone.utc)
                    stub_job = CanonicalJob(
                        canonical_job_id=target_job_id,
                        company_name="Unknown Orphan Job",
                        availability=PostingAvailability.UNKNOWN,
                        current_revision_id=uuid.uuid4(),
                        first_seen_at=now_ts,
                        last_seen_at=now_ts,
                    )
                    self.engine.canonical_jobs.save_canonical_job(stub_job)
                    stub_req = stub_req.model_copy(update={"canonical_job_id": target_job_id})

                self.engine.generation_requests.create_request(stub_req)
                self.engine.generation_work.save_projection_intent(fail_intent)
                self.projector.project_intent(fail_intent)

            actions.append(f"Projected failure for stale orphan remote Running request {obs.canonical_salesforce_id}")

        return actions

    def _parse_doc_type(self, val: Any) -> Any:
        from job_automation.contracts.enums import DocumentType
        try:
            return DocumentType(val)
        except Exception:
            return DocumentType.CV
