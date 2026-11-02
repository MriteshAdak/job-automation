"""Candidate-owned field preservation tests for SYNC-01 (SYNC-01-S05)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    PostingAvailability,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_records import (
    RemoteEntityMapping,
    SyncSubmission,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "salesforce" / "sync"
CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


def load_c11_fixture(filename: str) -> Assessment:
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Assessment.model_validate(data)


class TestCandidatePreservation:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_cand_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    @pytest.fixture
    def gateway(self) -> FakeSalesforceGatewayV2:
        return FakeSalesforceGatewayV2()

    def test_candidate_edits_survive_machine_updates(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        # 1. Save canonical job in local storage
        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=comp_id,
            company_name="Cloud Corp",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

        # 2. Initial publication of the eligible job
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-1",
            job_title="Software Architect",
            company_name="Cloud Corp",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)
        assert plan_res.is_published is True

        # Dispatch initial outbox write
        dispatcher = SyncDispatcher(engine)
        drain_1 = dispatcher.drain_due_work(gateway, config)
        assert drain_1.steps_succeeded == 2  # Company + Job

        # Retrieve remote record ID of the created job
        job_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.job_object, job_id)
        assert job_map is not None
        remote_job_id = job_map.salesforce_id

        # 3. Candidate edits their fields in Salesforce
        candidate_updates = {
            "Application_Progress__c": "Interviewing",
            "Candidate_Notes__c": "Passed screening, take-home project due Friday",
            "Candidate_Decision__c": "Shortlisted",
            "Follow_Up_Date__c": "2026-11-06",
            "Interview_Date__c": "2026-11-10",
        }
        gateway.simulate_candidate_edit(config.job_object, remote_job_id, candidate_updates)

        # 4. Ingestion detects the job availability has changed to unavailable -> queue refresh
        refresh_res = service.queue_tracked_refresh(
            canonical_job_id=job_id,
            new_availability=PostingAvailability.UNAVAILABLE,
            change_token="gen-avail-update",
            config=config,
        )
        assert refresh_res.is_published is True

        # 5. Dispatch machine update
        drain_2 = dispatcher.drain_due_work(gateway, config)
        assert drain_2.steps_succeeded == 1

        # 6. Verify remote Salesforce record:
        # Machine fields must be updated, but candidate-owned fields MUST be completely intact!
        remote_rec = gateway.records[config.job_object][remote_job_id]
        assert remote_rec[config.availability_field] == "Unavailable"  # Machine updated!
        assert remote_rec["Application_Progress__c"] == "Interviewing"  # Preserved!
        assert remote_rec["Candidate_Notes__c"] == "Passed screening, take-home project due Friday"  # Preserved!
        assert remote_rec["Candidate_Decision__c"] == "Shortlisted"  # Preserved!
        assert remote_rec["Follow_Up_Date__c"] == "2026-11-06"  # Preserved!
        assert remote_rec["Interview_Date__c"] == "2026-11-10"  # Preserved!

        # 7. Verify local candidate snapshot was captured
        latest_snap = engine.candidate_snapshots.get_latest_snapshot(job_id)
        assert latest_snap is not None
        assert latest_snap.candidate_fields["Application_Progress__c"] == "Interviewing"
        assert latest_snap.candidate_fields["Candidate_Decision__c"] == "Shortlisted"

