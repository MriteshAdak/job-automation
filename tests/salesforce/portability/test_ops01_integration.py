"""Tests for OPS-01 disaster recovery integration, verified export packaging, and isolated restore (SF-04-S05)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.operations.backup import create_backup
from job_automation.operations.records import OperationsSettings, RemoteCompleteness
from job_automation.operations.remote_export import assemble_remote_export
from job_automation.operations.restore import apply_restore, plan_restore
from job_automation.operations.verification import verify_backup
from job_automation.salesforce.export_service import CandidateExportService
from job_automation.salesforce.portability_settings import PortabilitySettings
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


class TestOps01Integration:
    @pytest.fixture
    def setup_env(self, tmp_path: Path) -> dict[str, Any]:
        """Set up data root, database, and verified export package."""
        data_root = tmp_path / "data_root"
        data_root.mkdir(parents=True, exist_ok=True)
        db_path = data_root / "database" / "job_automation.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        engine = StorageEngine(db_path=db_path)
        engine.migrate()

        config = SyncMappingConfig(expected_org_id="00D000000000001")
        port_settings = PortabilitySettings(
            export_root=str(tmp_path / "exports"),
            staging_root=str(tmp_path / "staging"),
            batch_size=10,
            require_company_closure=True,
            export_field_history=False,
        )

        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")
        now_dt = datetime.now(timezone.utc)

        c_uuid = uuid.uuid4()
        c_sf = "a00Comp001"
        gateway.records.setdefault("Company__c", {})[c_sf] = {
            "Id": c_sf,
            "Canonical_Company_Id__c": str(c_uuid),
            "Name": "Deutsche Bahn AG",
            "Company_Name__c": "Deutsche Bahn AG Berlin",
            "SystemModstamp": "2026-11-01T10:00:00Z",
        }

        j_uuid = uuid.uuid4()
        j_sf = "a00Job001"
        gateway.records.setdefault("Job__c", {})[j_sf] = {
            "Id": j_sf,
            "Canonical_Job_Id__c": str(j_uuid),
            "Company__c": c_sf,
            "Name": "Lead Developer",
            "Job_Title__c": "Lead Developer Automation",
            "Availability__c": "Active",
            "Assessment_Disposition__c": "Eligible",
            "Application_Progress__c": "Shortlisted",
            "Candidate_Notes__c": "Bewerbungsunterlagen vorbereitet (Prüfung).",
            "Candidate_Decision__c": "Starke Präferenz",
            "Follow_Up_Date__c": "2026-11-12",
            "Interview_Date__c": None,
            "SystemModstamp": "2026-11-01T10:05:00Z",
        }

        # Save local canonical job
        engine.canonical_jobs.save_canonical_job(
            CanonicalJob(
                canonical_job_id=j_uuid,
                canonical_company_id=c_uuid,
                company_name="Deutsche Bahn AG",
                current_revision_id=uuid.uuid4(),
                first_seen_at=now_dt,
                last_seen_at=now_dt,
            )
        )

        # Generate verified export package
        export_service = CandidateExportService(engine)
        manifest = export_service.export_candidate_data(gateway, config, port_settings)
        export_pkg_dir = list(Path(port_settings.export_root).glob("export_*"))[0]

        return {
            "data_root": data_root,
            "engine": engine,
            "config": config,
            "export_pkg_dir": export_pkg_dir,
            "job_uuid": j_uuid,
            "company_uuid": c_uuid,
        }

    def test_assemble_remote_export_with_verified_package(self, setup_env: dict[str, Any]) -> None:
        """Verified export package supplies complete remote recovery status to OPS-01."""
        engine = setup_env["engine"]
        config = setup_env["config"]
        export_dir = setup_env["export_pkg_dir"]

        remote_exp = assemble_remote_export(
            engine,
            config=config,
            export_dir=export_dir,
            max_freshness_hours=24.0,
        )

        assert remote_exp.completeness_status == RemoteCompleteness.COMPLETE
        assert remote_exp.saved_count == 1
        assert remote_exp.expected_count == 1
        assert str(setup_env["job_uuid"]) in remote_exp.per_record_tokens
        assert "Deutsche Bahn" in remote_exp.notes or "SF-04" in remote_exp.notes

    def test_backup_and_isolated_restore_with_umlauts(
        self, setup_env: dict[str, Any], tmp_path: Path
    ) -> None:
        """Backup packages remote export, independently verifies, and restores into a target with spaces and German umlauts."""
        engine = setup_env["engine"]
        data_root = setup_env["data_root"]
        config = setup_env["config"]
        export_dir = setup_env["export_pkg_dir"]

        ops_settings = OperationsSettings()
        backup_dest = tmp_path / "backups_archive"

        # 1. Create complete backup including remote export package
        manifest, backup_path = create_backup(
            settings=ops_settings,
            data_root=data_root,
            engine=engine,
            destination_override=backup_dest,
            local_only=False,
            sync_config=config,
            export_dir=export_dir,
        )

        assert manifest.completeness_status == "complete_local_and_remote"
        assert backup_path.is_dir()
        assert any(f.root_relative_path.startswith("remote_export/") for f in manifest.files)

        # 2. Verify backup independently
        is_valid, issues = verify_backup(backup_path)
        assert is_valid is True
        assert len(issues) == 0

        # 3. Restore into empty target directory containing spaces and German umlauts
        restore_target = tmp_path / "Wiederherstellung Prüfung" / "Drill 2026 Restore"
        plan = plan_restore(backup_path, restore_target, settings=ops_settings)
        assert plan.is_valid is True

        res = apply_restore(plan, settings=ops_settings)
        assert res.status.value == "succeeded"
        assert res.integrity_check_passed is True
        assert res.foreign_key_check_passed is True

        # Verify restored remote export files exist in restored target
        restored_export_manifest = restore_target / "remote_export" / "manifest.json"
        assert restored_export_manifest.is_file()
        restored_jobs = restore_target / "remote_export" / "jobs.jsonl"
        assert restored_jobs.is_file()
        restored_companies = restore_target / "remote_export" / "companies.jsonl"
        assert restored_companies.is_file()
        assert "Deutsche Bahn" in restored_companies.read_text(encoding="utf-8")
        assert "Prüfung" in restored_jobs.read_text(encoding="utf-8")
