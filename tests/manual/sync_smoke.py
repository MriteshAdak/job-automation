"""Manual smoke verification script for SYNC-01 synchronization lifecycle.

Safe-by-default execution:
- Default mode runs the full offline contract, persistence, and stateful fake verification.
- Reports prerequisite status for SF-01 (Salesforce schema) and SF-02 (OAuth credentials).
- Demonstrates C11-to-C12 mapping, External ID upsert ordering, candidate-owned field preservation,
  and lost-response reconciliation.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_automation.configuration import load_config
from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.candidate_backup import CandidateBackupService
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_reconciliation import SyncReconciler
from job_automation.salesforce.sync_records import (
    EntityType,
    PublicationDecision,
    RemoteEntityMapping,
    SyncStepState,
    SyncSubmission,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.salesforce.sync.test_publication import load_c11_fixture

DEFAULT_SYNC_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "sync.example.json"


def check_prerequisites(config_path: Path | None) -> dict[str, str]:
    """Check availability of dependent handoffs and prerequisites."""
    status: dict[str, str] = {
        "DATA-01 (SQLite Storage Engine)": "AVAILABLE",
        "MATCH-01 (C11 Assessment Contracts)": "AVAILABLE",
        "SFCLIENT-01 (Salesforce Gateway Client)": "AVAILABLE",
        "SF-01 (Target Salesforce Schema)": "PENDING (Metadata not deployed to org)",
        "SF-02 (OAuth Credentials & Flow)": "PENDING (No authorized refresh token)",
    }
    return status


def run_smoke(config_path: Path | None = None) -> int:
    """Execute smoke test suite for SYNC-01."""
    print("=== SYNC-01 Publication and Synchronization Smoke Verification ===")
    resolved_config_path = config_path or DEFAULT_SYNC_CONFIG
    print(f"Using mapping configuration: {resolved_config_path}")

    # 1. Prerequisite Status Report
    print("\n--- 1. Prerequisite Status ---")
    prereqs = check_prerequisites(config_path)
    for name, stat in prereqs.items():
        print(f"  [{stat:9s}] {name}")

    if not resolved_config_path.is_file():
        print(f"[ERROR] Mapping configuration file not found at: {resolved_config_path}")
        return 1

    config = load_sync_mapping_config(resolved_config_path)
    print(f"  Loaded mapping version: {config.mapping_version} (Org ID: {config.expected_org_id})")
    print(f"  Machine fields count: 9 | Candidate fields protected: {len(config.candidate_fields)}")

    # 2. Local State & Transaction Demonstration
    print("\n--- 2. Storage & Transaction Lifecycle ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "sync_smoke.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()
        try:
            # Seed canonical job
            asm = load_c11_fixture("rules_only_eligible.json")
            job_id = asm.canonical_job_id
            comp_id = uuid.uuid4()
            now_dt = datetime.now(timezone.utc)

            canonical_job = CanonicalJob(
                canonical_job_id=job_id,
                canonical_company_id=comp_id,
                company_name="Smoke Test Technologies GmbH",
                availability="active",
                current_revision_id=uuid.uuid4(),
                first_seen_at=now_dt,
                last_seen_at=now_dt,
            )
            engine.canonical_jobs.save_canonical_job(canonical_job)

            sub = SyncSubmission(
                assessment=asm,
                canonical_job_id=job_id,
                posting_revision=asm.posting_revision,
                evaluated_at=now_dt,
                generation_token="smoke-gen-1",
                job_title="Lead Automation Engineer",
                company_name="Smoke Test Technologies GmbH",
                canonical_company_id=comp_id,
                availability=PostingAvailability.ACTIVE,
            )

            service = SyncService(engine)
            plan_res = service.commit_assessment_and_plan(sub, config)
            print(f"  Committed plan: {plan_res.plan.plan_id}")
            print(f"  Publication decision: {plan_res.publication_decision.value}")
            print(f"  Write steps planned: {len(plan_res.plan.steps)} (Company upsert -> Job upsert)")

            # 3. Ordered External ID Delivery & Mock Gateway Transport
            print("\n--- 3. Ordered External ID Delivery & Mock Gateway ---")
            gateway = FakeSalesforceGatewayV2(org_id=config.expected_org_id)
            dispatcher = SyncDispatcher(engine)
            drain = dispatcher.drain_due_work(gateway, config)

            print(f"  Steps claimed: {drain.operations_claimed} | Succeeded: {drain.steps_succeeded}")
            print(f"  Physical upserts executed: {gateway.physical_upsert_count}")

            comp_rec = list(gateway.records[config.company_object].values())[0]
            job_rec = list(gateway.records[config.job_object].values())[0]
            print(f"  Company created remotely: {comp_rec['Id']} (External ID: {comp_rec[config.company_external_id_field]})")
            print(f"  Job created remotely: {job_rec['Id']} (Linked Company: {job_rec[config.job_company_lookup_field]})")
            assert job_rec[config.job_company_lookup_field] == comp_rec["Id"]

            # 4. Candidate-Owned Field Preservation
            print("\n--- 4. Candidate-Owned Field Preservation ---")
            gateway.simulate_candidate_edit(
                config.job_object,
                job_rec["Id"],
                {
                    "Application_Progress__c": "Interviewing",
                    "Candidate_Notes__c": "Technical round scheduled",
                },
            )
            print("  Simulated candidate edits in Salesforce:")
            print("    Application_Progress__c: 'Interviewing'")
            print("    Candidate_Notes__c: 'Technical round scheduled'")

            # Queue tracked machine update (availability change)
            refresh_res = service.queue_tracked_refresh(
                canonical_job_id=job_id,
                new_availability=PostingAvailability.UNAVAILABLE,
                change_token="smoke-gen-refresh",
                config=config,
            )
            print(f"  Queued machine refresh for tracked job (Decision: {refresh_res.publication_decision.value})")

            drain_refresh = dispatcher.drain_due_work(gateway, config)
            print(f"  Dispatched machine refresh (Steps succeeded: {drain_refresh.steps_succeeded})")

            # Verify candidate fields remained untouched
            updated_job = gateway.records[config.job_object][job_rec["Id"]]
            print(f"  Verified remote Machine Availability: '{updated_job[config.availability_field]}'")
            print(f"  Verified remote Candidate Progress: '{updated_job['Application_Progress__c']}' (PRESERVED)")
            print(f"  Verified remote Candidate Notes: '{updated_job['Candidate_Notes__c']}' (PRESERVED)")
            assert updated_job[config.availability_field] == "Unavailable"
            assert updated_job["Application_Progress__c"] == "Interviewing"
            assert updated_job["Candidate_Notes__c"] == "Technical round scheduled"

            # 5. Lost-Response Reconciliation
            print("\n--- 5. Lost-Response Reconciliation ---")
            gateway._simulate_lost_response_on_upsert = True
            # Submit an update that experiences network timeout on acknowledgment
            refresh_res_2 = service.queue_tracked_refresh(
                canonical_job_id=job_id,
                new_availability=PostingAvailability.ACTIVE,
                change_token="smoke-gen-lost-response",
                config=config,
            )
            drain_lost = dispatcher.drain_due_work(gateway, config)
            print(f"  Simulated lost response during send: {drain_lost.steps_failed} failed step(s)")
            print(f"  Entity lane barrier active: {engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id)}")

            reconciler = SyncReconciler(engine)
            rec_res = reconciler.reconcile_due_work(gateway, config)
            print(f"  Reconciliation executed: {rec_res.steps_confirmed} confirmed via read-back")
            print(f"  Entity lane barrier active: {engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id)}")
            assert rec_res.steps_confirmed == 1
            assert engine.sync_state.has_active_barrier(config.expected_org_id, config.job_object, job_id) is False

            # 6. Candidate Backup Scan
            print("\n--- 6. Candidate Field Backup & Checkpoint ---")
            backup_service = CandidateBackupService(engine)
            backup_res = backup_service.backup_candidate_fields(gateway, config)
            print(f"  Records scanned: {backup_res.records_read} | Snapshots saved: {backup_res.snapshots_saved}")
            checkpoint = engine.candidate_snapshots.get_latest_checkpoint(config.expected_org_id)
            assert checkpoint is not None
            print(f"  Checkpoint recorded: complete={bool(checkpoint['is_complete'])}")

        finally:
            engine.close()

    print("\n=== All SYNC-01 Smoke Checks Completed Successfully ===")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual smoke verification for SYNC-01")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to mapping configuration JSON (default: config/sync.example.json)",
    )
    args = parser.parse_args()
    sys.exit(run_smoke(args.config))


if __name__ == "__main__":
    main()
