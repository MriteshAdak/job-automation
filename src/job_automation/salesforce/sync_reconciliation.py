"""SYNC-01 reconciliation service for uncertain writes (SYNC-01-S07).

Enforces:
- External ID read-back for steps with uncertain transmission outcomes
- Matching reconciliation marker confirms lost successful responses
- Detecting newer remote versions and safely superseding older writes
- Retaining uncertainty barriers to prevent stale retries from overwriting newer remote facts
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import GetRecordRequest
from job_automation.salesforce.budget import CallBudget
from job_automation.salesforce.sync_ports import SyncDispatcherPort
from job_automation.salesforce.sync_records import (
    DrainResult,
    EntityType,
    ReconciliationResult,
    RemoteEntityMapping,
)
from job_automation.salesforce.sync_retry import MAX_RECONCILIATION_READS
from job_automation.salesforce.sync_settings import SyncMappingConfig

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class SyncReconciler:
    """Handles read-back reconciliation for ambiguous or interrupted sync operations."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def reconcile_due_work(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        budget: CallBudget | None = None,
        max_reconciliations: int = 50,
    ) -> ReconciliationResult:
        """Execute bounded reconciliation for uncertain write steps."""
        steps_checked = 0
        steps_confirmed = 0
        steps_superseded = 0
        barriers_retained = 0
        errors = []

        uncertain_steps = self.engine.sync_state.get_uncertain_steps(
            org_id=config.expected_org_id,
            limit=max_reconciliations,
        )

        for step in uncertain_steps:
            if budget and budget.is_exhausted():
                break

            steps_checked += 1
            now_utc = datetime.now(timezone.utc).isoformat()
            now_dt = datetime.now(timezone.utc)

            # Read remote record by External ID
            fields_to_read = [
                "Id",
                config.sync_marker_field,
                config.sync_version_field,
            ]
            req = GetRecordRequest(
                object_name=step.target_object,
                external_id_field=step.external_id_field,
                external_id_value=step.external_id_value,
                fields=fields_to_read,
            )

            res = gateway.get_record(req)
            if res.is_success and res.value is not None:
                remote_fields = res.value.fields
                remote_id = remote_fields.get("Id")
                remote_marker = remote_fields.get(config.sync_marker_field)
                remote_version_raw = remote_fields.get(config.sync_version_field)

                remote_version: int | None = None
                if remote_version_raw is not None:
                    try:
                        remote_version = int(remote_version_raw)
                    except (ValueError, TypeError):
                        pass

                # Case 1: Exact reconciliation marker match (or Company record exists by external ID)
                if (
                    (remote_marker == step.reconciliation_marker)
                    or (step.entity_type == EntityType.COMPANY and remote_id)
                ) and remote_id:
                    # Write confirmed! Commit acknowledgment, clear barrier, save mapping
                    self.engine.sync_state.mark_step_succeeded(
                        step_id=step.step_id,
                        remote_record_id=str(remote_id),
                        acknowledged_at_iso=now_utc,
                        confirmed_sequence=step.sequence_number,
                        org_id=config.expected_org_id,
                    )
                    mapping = RemoteEntityMapping(
                        org_id=config.expected_org_id,
                        object_name=step.target_object,
                        entity_id=step.entity_id,
                        external_id=step.external_id_value,
                        salesforce_id=str(remote_id),
                        confirmed_sequence=step.sequence_number,
                        reconciliation_marker=step.reconciliation_marker,
                        acknowledged_at=now_dt,
                    )
                    self.engine.sync_state.save_remote_mapping(mapping)
                    steps_confirmed += 1
                    continue

                # Case 2: Remote version is newer than this step
                elif remote_version is not None and remote_version > step.sequence_number:
                    # This older write was superseded by a newer confirmed update
                    self.engine.sync_state.supersede_step(
                        step_id=step.step_id,
                        reason=f"Remote sequence {remote_version} > step sequence {step.sequence_number}",
                    )
                    # Clear barrier on this step's entity lane
                    self.engine.sync_state.clear_barrier(
                        org_id=config.expected_org_id,
                        target_object=step.target_object,
                        entity_id=step.entity_id,
                    )
                    steps_superseded += 1
                    continue

                else:
                    # Remote record exists with different/older marker or no marker
                    # Retain barrier
                    barriers_retained += 1

            elif res.is_failure and res.failure is not None:
                # If 404 Not Found: the record does not exist remotely
                # But a delayed in-flight request could still commit, so we check attempt budget
                if res.failure.http_status == 404:
                    if step.attempt_count >= MAX_RECONCILIATION_READS:
                        # Bounded reconciliation reads reached without evidence of commit
                        # Mark failed, preserve barrier for safety
                        barriers_retained += 1
                    else:
                        barriers_retained += 1
                else:
                    errors.append(res.failure.error)
                    barriers_retained += 1

        return ReconciliationResult(
            steps_checked=steps_checked,
            steps_confirmed=steps_confirmed,
            steps_superseded=steps_superseded,
            barriers_retained=barriers_retained,
            errors=errors,
        )
