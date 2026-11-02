"""Candidate field backup scan and checkpoint tests for SYNC-01 (SYNC-01-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.candidate_backup import CandidateBackupService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


class TestCandidateBackup:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_backup_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    @pytest.fixture
    def gateway(self, engine: StorageEngine) -> FakeSalesforceGatewayV2:
        gw = FakeSalesforceGatewayV2()
        now_dt = datetime.now(timezone.utc)
        # Pre-seed 3 Job records in Salesforce and SQLite
        for i in range(1, 4):
            jid = uuid.uuid4()
            cid = uuid.uuid4()
            rid = f"a00Job00000000{i}AAA"
            canonical_job = CanonicalJob(
                canonical_job_id=jid,
                canonical_company_id=cid,
                company_name=f"Company {i}",
                availability="active",
                current_revision_id=uuid.uuid4(),
                first_seen_at=now_dt,
                last_seen_at=now_dt,
            )
            engine.canonical_jobs.save_canonical_job(canonical_job)
            gw.records.setdefault("Job__c", {})[rid] = {
                "Id": rid,
                "Canonical_Job_Id__c": str(jid),
                "Name": f"Role {i}",
                "Application_Progress__c": f"Status {i}",
                "Candidate_Notes__c": f"Notes for {i}",
                "Candidate_Decision__c": "Under Review",
                "Follow_Up_Date__c": f"2026-11-0{i}",
                "Interview_Date__c": None,
                "SystemModstamp": "mod-1",
            }
            gw.external_ids.setdefault("Job__c", {})[str(jid)] = rid
        return gw

    def test_backup_candidate_fields_scans_and_snapshots(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        service = CandidateBackupService(engine)
        res = service.backup_candidate_fields(gateway, config, batch_size=10)

        assert res.records_read == 3
        assert res.snapshots_saved == 3
        assert res.is_complete is True
        assert len(res.errors) == 0

        # Verify checkpoint is recorded
        cp = engine.candidate_snapshots.get_latest_checkpoint(config.expected_org_id)
        assert cp is not None
        assert cp["is_complete"] == 1
        assert cp["records_processed"] == 3
