"""Unit and contract tests for Salesforce metadata inventory, ownership audit, and staging verification (SF-04-S03)."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.salesforce.metadata_inventory import (
    audit_staged_metadata,
    check_cli_availability,
    classify_metadata_member,
    compare_staged_with_repository,
    compute_metadata_digest,
    load_ownership_registry,
    scan_file_for_secrets,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
METADATA_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"


class TestMetadataInventory:
    def test_load_ownership_registry(self) -> None:
        """Ownership registry must load and contain required project-owned metadata definitions."""
        reg = load_ownership_registry()
        assert "project_owned" in reg
        assert "unrelated_protected" in reg
        assert "CustomObject" in reg["project_owned"]
        assert "Company__c" in reg["project_owned"]["CustomObject"]
        assert "Job__c" in reg["project_owned"]["CustomObject"]

    def test_classify_members(self) -> None:
        """Members are strictly classified into project-owned, unrelated-protected, or unknown."""
        reg = load_ownership_registry()

        assert classify_metadata_member("CustomObject", "Job__c", reg) == "project-owned"
        assert (
            classify_metadata_member("CustomField", "Job__c.Candidate_Notes__c", reg)
            == "project-owned"
        )
        assert classify_metadata_member("PermissionSet", "Job_Automation_Worker", reg) == "project-owned"
        assert classify_metadata_member("StandardObject", "Account", reg) == "unrelated-protected"
        assert classify_metadata_member("Profile", "Admin", reg) == "unrelated-protected"
        assert classify_metadata_member("CustomField", "Job__c.Unowned_Test_Field__c", reg) == "unknown"

    def test_audit_detects_unowned_nested_files_and_quarantines(self, tmp_path: Path) -> None:
        """Retrieval returning unowned nested fields or unrelated objects must quarantine them."""
        # Create synthetic staged metadata with one valid job field and one unowned field
        staged_obj_dir = tmp_path / "objects" / "Job__c" / "fields"
        staged_obj_dir.mkdir(parents=True, exist_ok=True)

        valid_field = staged_obj_dir / "Candidate_Notes__c.field-meta.xml"
        valid_field.write_text("<CustomField xmlns='http://soap.sforce.com/2006/04/metadata'/>", encoding="utf-8")

        unowned_field = staged_obj_dir / "Intruder_Field__c.field-meta.xml"
        unowned_field.write_text("<CustomField xmlns='http://soap.sforce.com/2006/04/metadata'/>", encoding="utf-8")

        reg = load_ownership_registry()
        report = audit_staged_metadata(tmp_path, reg)

        assert report["is_valid"] is False
        assert any("Intruder_Field__c" in q for q in report["quarantine_files"])
        assert any("Candidate_Notes__c" in p for p in report["project_owned_files"])

    def test_audit_detects_secrets_and_credentials(self, tmp_path: Path) -> None:
        """Retrieved files containing client secrets or private keys must be flagged as security violations."""
        secret_file = tmp_path / "secret.xml"
        secret_file.write_text(
            "<oauthSettings><clientSecret>super_secret_oauth_secret_123</clientSecret></oauthSettings>",
            encoding="utf-8",
        )

        findings = scan_file_for_secrets(secret_file)
        assert len(findings) == 1
        assert "Potential secret" in findings[0]

        report = audit_staged_metadata(tmp_path)
        assert report["is_valid"] is False
        assert len(report["security_findings"]) >= 1

    def test_audit_detects_broad_profiles(self, tmp_path: Path) -> None:
        """Broad profiles in staged retrieval must be flagged and quarantined."""
        prof_dir = tmp_path / "profiles"
        prof_dir.mkdir(parents=True, exist_ok=True)
        admin_prof = prof_dir / "Admin.profile-meta.xml"
        admin_prof.write_text("<Profile xmlns='http://soap.sforce.com/2006/04/metadata'/>", encoding="utf-8")

        report = audit_staged_metadata(tmp_path)
        assert report["is_valid"] is False
        assert any("Broad profile detected" in s for s in report["security_findings"])

    def test_deterministic_metadata_digest(self) -> None:
        """Repository metadata digest must be deterministic across calls and non-empty."""
        d1 = compute_metadata_digest(METADATA_DIR)
        d2 = compute_metadata_digest(METADATA_DIR)
        assert len(d1) == 64
        assert d1 == d2

    def test_compare_staged_with_repository(self, tmp_path: Path) -> None:
        """Semantic comparison accurately identifies identical and modified files without modifying repo."""
        # Create identical copy of one file and one modified file
        staged_fields = tmp_path / "objects" / "Job__c" / "fields"
        staged_fields.mkdir(parents=True, exist_ok=True)

        repo_field = METADATA_DIR / "objects" / "Job__c" / "fields" / "Candidate_Notes__c.field-meta.xml"
        assert repo_field.is_file()

        # Identical
        (staged_fields / "Candidate_Notes__c.field-meta.xml").write_bytes(repo_field.read_bytes())

        # Modified
        (staged_fields / "Follow_Up_Date__c.field-meta.xml").write_text("<modified/>", encoding="utf-8")

        diff = compare_staged_with_repository(tmp_path, METADATA_DIR)
        assert any("Candidate_Notes__c" in f for f in diff["identical_files"])
        assert any("Follow_Up_Date__c" in f for f in diff["modified_files"])
        assert diff["has_unreviewed_changes"] is True

    def test_check_cli_availability(self) -> None:
        """CLI check returns cleanly without throwing unhandled exceptions."""
        is_avail, msg = check_cli_availability()
        assert isinstance(is_avail, bool)
        assert isinstance(msg, str)

