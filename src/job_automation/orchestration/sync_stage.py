"""Salesforce sync stage coordinator (RUN-01-S07).

Coordinates:
1. Publication planning for selected assessments and refreshed tracked jobs (T1)
2. Bounded uncertainty reconciliation for interrupted remote calls
3. Bounded ordered outbox dispatch (Company-before-Job)
4. Bounded candidate-owned field backup without blocking writes on backup failure
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Sequence

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import SyncOperationState
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.orchestration.records import RunAttempt, RunRequest
from job_automation.salesforce.budget import CallBudget
from job_automation.salesforce.candidate_backup import CandidateBackupService
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_ports import (
    CandidateBackupPort,
    SyncDispatcherPort,
    SyncServicePort,
)
from job_automation.salesforce.sync_records import (
    CandidateBackupResult,
    DrainResult,
    PublicationDecision,
    ReconciliationResult,
    SyncPlanResult,
    SyncSubmission,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import SyncMappingConfig

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class SyncStageResult(ContractModel):
    """Aggregate result of the Salesforce sync stage."""

    plans_created: int = 0
    published_initial: int = 0
    updated_tracked: int = 0
    local_only_rejected: int = 0
    local_only_comparison: int = 0
    no_change: int = 0
    plan_results: list[SyncPlanResult] = []
    reconciliation_result: ReconciliationResult | None = None
    drain_result: DrainResult | None = None
    backup_result: CandidateBackupResult | None = None
    sync_operations_succeeded: int = 0
    sync_operations_failed: int = 0
    pending_operations_count: int = 0
    errors: list[ClassifiedError] = []


class SyncStageCoordinator:
    """Coordinates publication planning, reconciliation, drain, and backup."""

    def __init__(
        self,
        engine: StorageEngine,
        sync_service: SyncServicePort | None = None,
        dispatcher: SyncDispatcherPort | None = None,
        backup_service: CandidateBackupPort | None = None,
    ) -> None:
        self.engine = engine
        self.sync_service = sync_service or SyncService(engine)
        self.dispatcher = dispatcher or SyncDispatcher(engine)
        self.backup_service = backup_service or CandidateBackupService(engine)

    def plan_submissions(
        self,
        submissions: Sequence[SyncSubmission],
        config: SyncMappingConfig,
    ) -> list[SyncPlanResult]:
        """Atomically persist assessments and publication plans."""
        results: list[SyncPlanResult] = []
        for sub in submissions:
            plan_res = self.sync_service.commit_assessment_and_plan(sub, config)
            results.append(plan_res)
        return results

    def execute_sync(
        self,
        request: RunRequest,
        attempt: RunAttempt,
        submissions: Sequence[SyncSubmission],
        config: SyncMappingConfig,
        gateway: SalesforceGatewayV2 | None = None,
        budget: CallBudget | None = None,
        worker_id: str | None = None,
        run_candidate_backup: bool = True,
        max_drain_operations: int = 100,
    ) -> SyncStageResult:
        """Execute atomic planning, followed by optional remote reconciliation, drain, and backup."""
        errors: list[ClassifiedError] = []

        # 1. Plan submissions
        plan_results = self.plan_submissions(submissions, config)

        published_initial = 0
        updated_tracked = 0
        local_only_rejected = 0
        local_only_comparison = 0
        no_change = 0

        for pr in plan_results:
            if pr.publication_decision == PublicationDecision.PUBLISH_INITIAL:
                published_initial += 1
            elif pr.publication_decision == PublicationDecision.UPDATE_TRACKED:
                updated_tracked += 1
            elif pr.publication_decision == PublicationDecision.LOCAL_ONLY_REJECTED:
                local_only_rejected += 1
            elif pr.publication_decision == PublicationDecision.LOCAL_ONLY_COMPARISON:
                local_only_comparison += 1
            elif pr.publication_decision == PublicationDecision.NO_CHANGE:
                no_change += 1

        reconciliation_result: ReconciliationResult | None = None
        drain_result: DrainResult | None = None
        backup_result: CandidateBackupResult | None = None

        if gateway is not None:
            # 2. Reconcile due work (uncertainty barriers from interrupted past attempts)
            try:
                reconciliation_result = self.dispatcher.reconcile_due_work(
                    gateway=gateway,
                    config=config,
                    budget=budget,
                )
                if reconciliation_result.errors:
                    errors.extend(reconciliation_result.errors)
            except Exception as exc:
                logger.exception("Error during sync reconciliation")
                errors.append(
                    ClassifiedError(
                        category=ErrorCategory.TRANSIENT_SERVICE,
                        message=f"Reconciliation error: {exc}",
                        recoverable=True,
                    )
                )

            # 3. Drain due work
            active_worker_id = worker_id or f"worker-{attempt.run_id}"
            try:
                drain_result = self.dispatcher.drain_due_work(
                    gateway=gateway,
                    config=config,
                    budget=budget,
                    worker_id=active_worker_id,
                    max_operations=max_drain_operations,
                )
                if drain_result.errors:
                    errors.extend(drain_result.errors)
            except Exception as exc:
                logger.exception("Error during sync drain")
                errors.append(
                    ClassifiedError(
                        category=ErrorCategory.TRANSIENT_SERVICE,
                        message=f"Sync drain error: {exc}",
                        recoverable=True,
                    )
                )

            # 4. Candidate Backup
            if run_candidate_backup:
                try:
                    backup_result = self.backup_service.backup_candidate_fields(
                        gateway=gateway,
                        config=config,
                    )
                    if backup_result.errors:
                        errors.extend(backup_result.errors)
                except Exception as exc:
                    logger.exception("Error during candidate backup")
                    backup_result = CandidateBackupResult(
                        records_read=0,
                        snapshots_saved=0,
                        is_complete=False,
                        errors=[
                            ClassifiedError(
                                category=ErrorCategory.TRANSIENT_SERVICE,
                                message=f"Candidate backup error: {exc}",
                                recoverable=True,
                            )
                        ],
                    )
                    errors.extend(backup_result.errors)

        # 5. Calculate distinct C12 operations succeeded, failed, and pending
        operations_succeeded = 0
        operations_failed = 0
        operations_pending = 0

        # Check all C12 operations generated in this batch
        observed_op_ids: set[uuid.UUID] = set()
        for pr in plan_results:
            if pr.sync_operation:
                op_id = pr.sync_operation.operation_id
                observed_op_ids.add(op_id)
                persisted_op = self.engine.sync_state.get_sync_operation(op_id)
                if persisted_op:
                    if persisted_op.state == SyncOperationState.SUCCEEDED:
                        operations_succeeded += 1
                    elif persisted_op.state == SyncOperationState.FAILED:
                        operations_failed += 1
                    else:
                        operations_pending += 1

        # Check any pending operations across the system if gateway ran
        if gateway is None:
            # In offline/no-gateway mode, all generated publishable operations remain pending
            operations_pending = len(observed_op_ids)

        return SyncStageResult(
            plans_created=len(plan_results),
            published_initial=published_initial,
            updated_tracked=updated_tracked,
            local_only_rejected=local_only_rejected,
            local_only_comparison=local_only_comparison,
            no_change=no_change,
            plan_results=plan_results,
            reconciliation_result=reconciliation_result,
            drain_result=drain_result,
            backup_result=backup_result,
            sync_operations_succeeded=operations_succeeded,
            sync_operations_failed=operations_failed,
            pending_operations_count=operations_pending,
            errors=errors,
        )
