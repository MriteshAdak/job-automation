"""SYNC-01 ordered outbox dispatcher and drain worker (SYNC-01-S06, S08).

Enforces:
- Company-before-Job write ordering
- Compare-and-set step claiming (T2)
- Atomic acknowledgment and mapping persistence (T3)
- Preservation of candidate-owned fields prior to updates and post-creation default capture
- Uncertainty barrier retention on ambiguous outcomes
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import (
    RemoteOutcome,
    UpsertRequest,
)
from job_automation.salesforce.budget import CallBudget
from job_automation.salesforce.candidate_backup import CandidateBackupService
from job_automation.salesforce.sync_ports import SyncDispatcherPort
from job_automation.salesforce.sync_reconciliation import SyncReconciler
from job_automation.salesforce.sync_records import (
    DrainResult,
    EntityType,
    ReconciliationResult,
    RemoteEntityMapping,
    SyncStepState,
)
from job_automation.salesforce.sync_retry import (
    DEFAULT_MAX_ATTEMPTS,
    compute_next_attempt_at,
    is_safely_retryable,
)
from job_automation.salesforce.sync_settings import SyncMappingConfig

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class SyncDispatcher(SyncDispatcherPort):
    """Production implementation of SyncDispatcherPort."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine
        self.reconciler = SyncReconciler(engine)
        self.backup_service = CandidateBackupService(engine)

    def reconcile_due_work(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        budget: CallBudget | None = None,
        max_reconciliations: int = 50,
    ) -> ReconciliationResult:
        """Execute bounded reconciliation for uncertain write steps."""
        return self.reconciler.reconcile_due_work(
            gateway=gateway,
            config=config,
            budget=budget,
            max_reconciliations=max_reconciliations,
        )

    def drain_due_work(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        budget: CallBudget | None = None,
        worker_id: str = "worker-1",
        max_operations: int = 100,
    ) -> DrainResult:
        """Execute due write steps in per-entity order with compare-and-set claims."""
        operations_claimed = 0
        steps_succeeded = 0
        steps_failed = 0
        errors = []

        now_utc = datetime.now(timezone.utc).isoformat()
        now_dt = datetime.now(timezone.utc)

        while operations_claimed < max_operations:
            if budget and budget.is_exhausted():
                break

            due_steps = self.engine.sync_state.get_due_steps(
                org_id=config.expected_org_id,
                limit=max_operations - operations_claimed,
                now_iso=now_utc,
            )
            if not due_steps:
                break

            progress_made = False
            for step in due_steps:
                if budget and budget.is_exhausted():
                    break

                # 1. Enforce per-entity lane barriers
                if self.engine.sync_state.has_active_barrier(
                    org_id=config.expected_org_id,
                    target_object=step.target_object,
                    entity_id=step.entity_id,
                ):
                    continue

                # 2. Enforce step dependencies (e.g. Job requires prior Company step)
                if step.depends_on_step_id is not None:
                    parent_step = self.engine.sync_state.get_step(step.depends_on_step_id)
                    if parent_step is None or parent_step.state != SyncStepState.SUCCEEDED:
                        # Parent step not yet confirmed; cannot dispatch dependent step
                        continue

                    # Inject resolved parent Salesforce record ID into lookup relationship
                    if step.relationship_field and parent_step.remote_record_id:
                        step.frozen_payload[step.relationship_field] = parent_step.remote_record_id

                # 3. Compare-and-set claim (T2 send intent)
                claimed = self.engine.sync_state.claim_step(
                    step_id=step.step_id,
                    worker_id=worker_id,
                    now_iso=now_utc,
                )
                if not claimed:
                    continue

                operations_claimed += 1
                progress_made = True

                # 4. If updating an already-tracked Job, snapshot candidate fields before overwriting machine facts
                if step.entity_type == EntityType.JOB:
                    job_mapping = self.engine.sync_state.get_remote_mapping(
                        org_id=config.expected_org_id,
                        target_object=step.target_object,
                        entity_id=step.entity_id,
                    )
                    if job_mapping is not None:
                        self.backup_service.read_and_snapshot_candidate_fields(
                            canonical_job_id=step.entity_id,
                            remote_record_id=job_mapping.salesforce_id,
                            gateway=gateway,
                            config=config,
                        )

                # 5. Execute upsert by External ID
                upsert_req = UpsertRequest(
                    object_name=step.target_object,
                    external_id_field=step.external_id_field,
                    external_id_value=step.external_id_value,
                    fields=step.frozen_payload,
                )

                upsert_res = gateway.upsert_by_external_id(upsert_req)

                # 6. Process outcome
                if upsert_res.is_success and upsert_res.value is not None:
                    remote_id = upsert_res.value.record_id
                    is_created = upsert_res.value.created

                    # T3: Commit step success, advance confirmed sequence, update C12
                    self.engine.sync_state.mark_step_succeeded(
                        step_id=step.step_id,
                        remote_record_id=remote_id,
                        acknowledged_at_iso=now_utc,
                        confirmed_sequence=step.sequence_number,
                        org_id=config.expected_org_id,
                    )

                    # Persist confirmed mapping in sync_remote_mappings
                    mapping = RemoteEntityMapping(
                        org_id=config.expected_org_id,
                        object_name=step.target_object,
                        entity_id=step.entity_id,
                        external_id=step.external_id_value,
                        salesforce_id=remote_id,
                        confirmed_sequence=step.sequence_number,
                        reconciliation_marker=step.reconciliation_marker,
                        acknowledged_at=now_dt,
                    )
                    self.engine.sync_state.save_remote_mapping(mapping)

                    # For newly created jobs, read back creation defaults into snapshot
                    if step.entity_type == EntityType.JOB and is_created:
                        self.backup_service.read_and_snapshot_candidate_fields(
                            canonical_job_id=step.entity_id,
                            remote_record_id=remote_id,
                            gateway=gateway,
                            config=config,
                        )

                    steps_succeeded += 1

                elif upsert_res.is_failure and upsert_res.failure is not None:
                    failure = upsert_res.failure
                    errors.append(failure.error)

                    if failure.remote_outcome == RemoteOutcome.UNKNOWN:
                        # Uncertain outcome: retain barrier on this lane!
                        next_att = compute_next_attempt_at(step.attempt_count + 1, failure=failure)
                        self.engine.sync_state.mark_step_failed(
                            step_id=step.step_id,
                            error=failure.error,
                            next_attempt_at_iso=next_att.isoformat(),
                            is_terminal=False,
                            retain_barrier=True,
                            barrier_reason=f"Uncertain transmission: {failure.error.message}",
                            org_id=config.expected_org_id,
                        )
                    elif (not is_safely_retryable(failure)) or (step.attempt_count + 1 >= DEFAULT_MAX_ATTEMPTS):
                        # Terminal failure (permission, invalid config, or retry limit exhausted)
                        self.engine.sync_state.mark_step_failed(
                            step_id=step.step_id,
                            error=failure.error,
                            next_attempt_at_iso=None,
                            is_terminal=True,
                            retain_barrier=False,
                            org_id=config.expected_org_id,
                        )
                    else:
                        # Safely retryable transient failure
                        next_att = compute_next_attempt_at(step.attempt_count + 1, failure=failure)
                        self.engine.sync_state.mark_step_failed(
                            step_id=step.step_id,
                            error=failure.error,
                            next_attempt_at_iso=next_att.isoformat(),
                            is_terminal=False,
                            retain_barrier=False,
                            org_id=config.expected_org_id,
                        )

                    steps_failed += 1

            if not progress_made:
                break

        # Calculate remaining due work
        remaining = self.engine.sync_state.get_due_steps(
            org_id=config.expected_org_id,
            limit=max_operations,
            now_iso=now_utc,
        )

        return DrainResult(
            operations_claimed=operations_claimed,
            steps_succeeded=steps_succeeded,
            steps_failed=steps_failed,
            remaining_due=len(remaining),
            errors=errors,
        )
