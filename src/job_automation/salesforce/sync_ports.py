"""SYNC-01 boundary interfaces and Protocols (SYNC-01-S01).

Defines:
- SyncServicePort: submission, planning, and tracked refreshes
- SyncDispatcherPort: ordered outbox dispatch and uncertain-write reconciliation
- CandidateBackupPort: candidate field read-back and local snapshot capture
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.salesforce.budget import CallBudget
from job_automation.salesforce.sync_records import (
    CandidateBackupResult,
    CandidateFieldSnapshot,
    DrainResult,
    ReconciliationResult,
    SyncPlanResult,
    SyncSubmission,
)
from job_automation.salesforce.sync_settings import SyncMappingConfig


@runtime_checkable
class SyncServicePort(Protocol):
    """Boundary for assessment planning and atomic outbox enqueue."""

    def register_selection_token(
        self,
        canonical_job_id: uuid.UUID,
        generation_token: str,
    ) -> None:
        """Register or advance the active input-generation token for a job."""
        ...

    def commit_assessment_and_plan(
        self,
        submission: SyncSubmission,
        config: SyncMappingConfig,
    ) -> SyncPlanResult:
        """Atomically persist assessment and evaluate/enqueue Salesforce sync plan."""
        ...

    def queue_tracked_refresh(
        self,
        canonical_job_id: uuid.UUID,
        new_availability: PostingAvailability,
        change_token: str,
        config: SyncMappingConfig,
        run_id: str | None = None,
    ) -> SyncPlanResult:
        """Queue updated machine facts (availability) for an already tracked job."""
        ...


@runtime_checkable
class SyncDispatcherPort(Protocol):
    """Boundary for ordered outbox delivery and reconciliation."""

    def drain_due_work(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        budget: CallBudget | None = None,
        worker_id: str = "worker-1",
        max_operations: int = 100,
    ) -> DrainResult:
        """Execute due write steps in per-entity order with compare-and-set claims."""
        ...

    def reconcile_due_work(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        budget: CallBudget | None = None,
        max_reconciliations: int = 50,
    ) -> ReconciliationResult:
        """Reconcile uncertain write steps via External ID read-back."""
        ...


@runtime_checkable
class CandidateBackupPort(Protocol):
    """Boundary for candidate field reading and local snapshot persistence."""

    def read_and_snapshot_candidate_fields(
        self,
        canonical_job_id: uuid.UUID,
        remote_record_id: str,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
    ) -> CandidateFieldSnapshot | None:
        """Read and snapshot candidate fields before a machine update."""
        ...

    def backup_candidate_fields(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        batch_size: int = 50,
    ) -> CandidateBackupResult:
        """Bounded backup pass across all tracked jobs."""
        ...

