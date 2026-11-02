"""Tests for independent offline export verification (SF-04-S05)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
import pytest

from job_automation.salesforce.export_service import CandidateExportService
from job_automation.salesforce.export_verification import verify_export_package
from job_automation.salesforce.portability_settings import PortabilitySettings
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


class TestExportVerification:
    @pytest.fixture
    def valid_export_dir(self, tmp_path: Path) -> Path:
        """Create a valid synthetic export package on disk."""
        db_path = tmp_path / "test_ver.db"
        eng = StorageEngine(db_path=db_path)
        eng.migrate()

        config = SyncMappingConfig(expected_org_id="00D000000000001")
        settings = PortabilitySettings(
            export_root=str(tmp_path / "exports"),
            staging_root=str(tmp_path / "staging"),
            batch_size=10,
            require_company_closure=True,
            export_field_history=False,
        )

        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001")
        c_uuid = uuid.uuid4()
        c_sf = "a00Comp001"
        gateway.records.setdefault("Company__c", {})[c_sf] = {
            "Id": c_sf,
            "Canonical_Company_Id__c": str(c_uuid),
            "Name": "SAP SE",
            "SystemModstamp": "2026-11-01T10:00:00Z",
        }

        j_uuid = uuid.uuid4()
        j_sf = "a00Job001"
        gateway.records.setdefault("Job__c", {})[j_sf] = {
            "Id": j_sf,
            "Canonical_Job_Id__c": str(j_uuid),
            "Company__c": c_sf,
            "Name": "Cloud Architect",
            "Application_Progress__c": "Applied",
            "Candidate_Notes__c": "Bewerbung abgeschickt über Portal.",
            "Candidate_Decision__c": None,
            "Follow_Up_Date__c": "2026-11-20",
            "Interview_Date__c": None,
            "SystemModstamp": "2026-11-01T10:05:00Z",
        }

        service = CandidateExportService(eng)
        manifest = service.export_candidate_data(gateway, config, settings)
        eng.close()

        dest_root = Path(settings.export_root)
        pkg_dir = list(dest_root.glob("export_*"))[0]
        return pkg_dir

    def test_verify_valid_export_package_passes(self, valid_export_dir: Path) -> None:
        """A valid complete package passes all verification checks."""
        report = verify_export_package(
            valid_export_dir,
            expected_org_id="00D000000000001",
            expected_mapping_version="1.0",
        )
        assert report.is_valid is True
        assert report.completeness_status == "complete"
        assert len(report.issues) == 0
        assert "jobs.jsonl" in report.checked_files
        assert "companies.jsonl" in report.checked_files
        assert report.total_records["jobs.jsonl"] == 1
        assert report.total_records["companies.jsonl"] == 1

    def test_verify_detects_file_hash_tampering(self, valid_export_dir: Path) -> None:
        """Modifying bytes of an exported file must trigger cryptographic hash mismatch."""
        jobs_file = valid_export_dir / "jobs.jsonl"
        # Tamper with file
        content = jobs_file.read_text(encoding="utf-8")
        jobs_file.write_text(content.replace("Applied", "TamperedStatus"), encoding="utf-8")

        report = verify_export_package(valid_export_dir)
        assert report.is_valid is False
        assert any("Cryptographic hash mismatch" in i for i in report.issues)

    def test_verify_detects_missing_file(self, valid_export_dir: Path) -> None:
        """Deleting a declared file from the package must fail verification."""
        comp_file = valid_export_dir / "companies.jsonl"
        comp_file.unlink()

        report = verify_export_package(valid_export_dir)
        assert report.is_valid is False
        assert any("Packaged file missing" in i for i in report.issues)

    def test_verify_detects_path_traversal(self, valid_export_dir: Path) -> None:
        """Manifest entries attempting path traversal must be rejected."""
        manifest_file = valid_export_dir / "manifest.json"
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        # Inject malicious file entry
        data["files"].append(
            {
                "relative_path": "../../Windows/System32/cmd.exe",
                "size_bytes": 100,
                "sha256": "fakehash",
                "record_count": 1,
            }
        )
        manifest_file.write_text(json.dumps(data), encoding="utf-8")

        report = verify_export_package(valid_export_dir)
        assert report.is_valid is False
        assert any("path traversal" in i.lower() for i in report.issues)

    def test_verify_detects_broken_company_closure(self, valid_export_dir: Path) -> None:
        """When jobs reference a company not in companies.jsonl, closure check fails."""
        # Clear companies.jsonl
        comp_file = valid_export_dir / "companies.jsonl"
        comp_file.write_text("", encoding="utf-8")

        # Update manifest hash for companies.jsonl so hash check passes, but closure fails
        manifest_file = valid_export_dir / "manifest.json"
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        for f in data["files"]:
            if f["relative_path"] == "companies.jsonl":
                f["size_bytes"] = 0
                f["sha256"] = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                f["record_count"] = 0
        manifest_file.write_text(json.dumps(data), encoding="utf-8")

        report = verify_export_package(valid_export_dir)
        assert report.is_valid is False
        assert any("Relationship closure failure" in i for i in report.issues)

    def test_verify_detects_org_id_mismatch(self, valid_export_dir: Path) -> None:
        """Package bound to a different org ID must report mismatch."""
        report = verify_export_package(
            valid_export_dir,
            expected_org_id="00D999999999999",  # Wrong org
        )
        assert report.is_valid is False
        assert any("Org ID mismatch" in i for i in report.issues)
