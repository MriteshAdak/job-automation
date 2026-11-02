"""Tests for CandidateExportService, keyset pagination, and candidate data capture (SF-04-S04)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.export_service import CandidateExportService
from job_automation.salesforce.portability_settings import PortabilitySettings
from job_automation.salesforce.sync_records import CandidateFieldSnapshot
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


class TestCandidateExportService:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "test_export.db"
        eng = StorageEngine(db_path=db_path)
        eng.migrate()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return SyncMappingConfig(expected_org_id="00D000000000001")

    @pytest.fixture
    def settings(self, tmp_path: Path) -> PortabilitySettings:
        return PortabilitySettings(
            export_root=str(tmp_path / "exports"),
            staging_root=str(tmp_path / "staging"),
            batch_size=2,  # Force multiple pages
            require_company_closure=True,
            export_field_history=False,
        )

    def test_export_pagination_multiple_pages(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        settings: PortabilitySettings,
    ) -> None:
        """Export traverses multiple pages via keyset pagination without stopping at batch LIMIT."""
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")

        # Create 1 Company
        c_uuid = uuid.uuid4()
        c_sf_id = "a00Comp000000001"
        gateway.records.setdefault("Company__c", {})[c_sf_id] = {
            "Id": c_sf_id,
            "Canonical_Company_Id__c": str(c_uuid),
            "Name": "Siemens AG",
            "Company_Name__c": "Siemens AG Berlin",
            "SystemModstamp": "2026-11-01T10:00:00Z",
        }

        # Create 5 Jobs (with batch_size=2, requires 3 pages)
        for i in range(1, 6):
            j_uuid = uuid.uuid4()
            j_sf_id = f"a00Job00000000{i}"
            gateway.records.setdefault("Job__c", {})[j_sf_id] = {
                "Id": j_sf_id,
                "Canonical_Job_Id__c": str(j_uuid),
                "Company__c": c_sf_id,
                "Name": f"Engineer Position {i}",
                "Job_Title__c": f"Senior Automation Engineer {i}",
                "Availability__c": "Active",
                "Assessment_Disposition__c": "Eligible",
                "Application_Progress__c": "Review",
                "Candidate_Notes__c": f"Notizen für Position {i} mit Prüfung.",
                "Candidate_Decision__c": "Favorit",
                "Follow_Up_Date__c": f"2026-11-0{i}",
                "Interview_Date__c": None,
                "SystemModstamp": f"2026-11-01T10:0{i}:00Z",
            }

        service = CandidateExportService(engine)
        manifest = service.export_candidate_data(gateway, config, settings)

        assert manifest.saved_counts["jobs"] == 5
        assert manifest.saved_counts["companies"] == 1
        assert manifest.pagination_completed is True
        assert manifest.completeness_status == "complete"

        # Verify export directory on disk
        dest_root = Path(settings.export_root)
        export_dirs = list(dest_root.glob("export_*"))
        assert len(export_dirs) == 1
        pkg_dir = export_dirs[0]

        jobs_file = pkg_dir / "jobs.jsonl"
        assert jobs_file.is_file()
        job_lines = [json.loads(l) for l in jobs_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(job_lines) == 5

        # Check candidate notes & German characters
        first_job = job_lines[0]
        assert "Prüfung" in first_job["candidate_notes"]
        assert first_job["canonical_company_id"] == str(c_uuid)
        assert first_job["interview_date"] is None  # Explicit null preserved

    def test_export_missing_parent_company_records_issue(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        settings: PortabilitySettings,
    ) -> None:
        """When a Job references an unknown Company ID, issue is recorded and completeness is partial."""
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")

        j_uuid = uuid.uuid4()
        j_sf_id = "a00Job000000099"
        gateway.records.setdefault("Job__c", {})[j_sf_id] = {
            "Id": j_sf_id,
            "Canonical_Job_Id__c": str(j_uuid),
            "Company__c": "a00CompNonExistent",  # Broken lookup
            "Name": "Orphan Role",
            "Application_Progress__c": "New",
            "SystemModstamp": "2026-11-01T10:00:00Z",
        }

        service = CandidateExportService(engine)
        manifest = service.export_candidate_data(gateway, config, settings)

        assert manifest.completeness_status == "partial"
        assert manifest.error_counts["jobs"] >= 1

        dest_root = Path(settings.export_root)
        pkg_dir = list(dest_root.glob("export_*"))[0]
        issues_file = pkg_dir / "issues.jsonl"
        assert issues_file.is_file()
        issues_lines = [json.loads(l) for l in issues_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert any(i["issue_type"] == "missing_parent_company" for i in issues_lines)

    def test_export_invalid_uuid_records_issue(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        settings: PortabilitySettings,
    ) -> None:
        """When a Job contains a non-UUID external ID, issue is recorded and completeness is partial."""
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")

        gateway.records.setdefault("Job__c", {})["a00Job001"] = {
            "Id": "a00Job001",
            "Canonical_Job_Id__c": "invalid-not-a-uuid",
            "Name": "Bad ID Role",
            "SystemModstamp": "2026-11-01T10:00:00Z",
        }

        service = CandidateExportService(engine)
        manifest = service.export_candidate_data(gateway, config, settings)

        assert manifest.completeness_status == "partial"
        assert manifest.error_counts["jobs"] >= 1

    def test_export_empty_scope_completes_cleanly(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        settings: PortabilitySettings,
    ) -> None:
        """Empty remote scope completes cleanly with 0 records and complete status."""
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")
        service = CandidateExportService(engine)

        manifest = service.export_candidate_data(gateway, config, settings)
        assert manifest.saved_counts["jobs"] == 0
        assert manifest.saved_counts["companies"] == 0
        assert manifest.completeness_status == "complete"
        assert "Zero remote jobs" in manifest.notes

