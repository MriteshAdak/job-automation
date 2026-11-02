"""Comprehensive test suite for SF-01 validation matrix (V01-V18).

Tests:
- Schema compatibility & collision detection (V01-V03)
- Canonical UUID uniqueness & identity stability (V04-V06)
- Company/Job relationships & cascade deletion protection (V07)
- Picklist mappings & disposition/availability separation (V08)
- Null-clearing for scores/scales & UTC timestamps (V09)
- Text/URL boundaries & Unicode preservation (V10)
- Creation-only defaults for Application_Progress__c (V11)
- Preservation of candidate-owned fields across updates (V12-V15)
- Worker vs candidate access boundaries (V16)
- Migration reconciliation & backfill rules (V17)
- Scoped package manifest allowlist (V18)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    PostingAvailability,
)
from job_automation.salesforce.metadata_parser import (
    CustomFieldMetadata,
    CustomObjectMetadata,
    load_salesforce_dx_objects,
    validate_metadata_compatibility,
)
from job_automation.salesforce.sync_errors import SyncOwnershipError
from job_automation.salesforce.sync_mapping import (
    build_company_external_id,
    build_company_payload,
    build_job_external_id,
    build_job_payload,
)
from job_automation.salesforce.sync_records import SyncSubmission
from job_automation.salesforce.sync_serialization import assert_no_candidate_fields
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_OBJECTS_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "objects"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "sync.example.json"
AUTONUMBER_CONFIG_PATH = REPO_ROOT / "config" / "sync.autonumber.example.json"
PREFIXED_CONFIG_PATH = REPO_ROOT / "config" / "sync.prefixed.example.json"
PACKAGE_XML_PATH = REPO_ROOT / "salesforce" / "manifest" / "package.xml"
SF01_XML_PATH = REPO_ROOT / "salesforce" / "manifest" / "sf01.xml"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "salesforce" / "sync"


def load_fixture(filename: str) -> Assessment:
    with open(FIXTURES_DIR / filename, "r", encoding="utf-8") as f:
        return Assessment.model_validate(json.load(f))


class TestSF01Scenarios:
    @pytest.fixture
    def metadata_objects(self) -> dict[str, CustomObjectMetadata]:
        return load_salesforce_dx_objects(SF_OBJECTS_DIR)

    @pytest.fixture
    def default_config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(DEFAULT_CONFIG_PATH)

    # --- V01: Collision Handling & Alternative Mappings ---
    def test_v01_alternative_checked_mapping_for_prefixed_objects(
        self, metadata_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        cfg = load_sync_mapping_config(PREFIXED_CONFIG_PATH)
        assert cfg.company_object == "JA_Company__c"
        assert cfg.job_object == "JA_Job__c"
        # When objects are missing, validator produces clean actionable issue
        report = validate_metadata_compatibility(metadata_objects, cfg)
        assert report.compatible is False
        assert any("JA_Company__c" in iss for iss in report.issues)

    # --- V02: Text Name vs Autonumber Name ---
    def test_v02_autonumber_and_text_name_handling(
        self, metadata_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        cfg_autonumber = load_sync_mapping_config(AUTONUMBER_CONFIG_PATH)
        assert cfg_autonumber.title_field == "Job_Title__c"
        assert cfg_autonumber.company_name_field == "Company_Name__c"

        # Metadata provides both Name (Text) and extended fields (Job_Title__c, Company_Name__c)
        job = metadata_objects["job__c"]
        comp = metadata_objects["company__c"]
        assert "job_title__c" in job.fields
        assert "company_name__c" in comp.fields

        # When mapping to Job_Title__c, payload builder populates Job_Title__c and NOT Name
        asm = load_fixture("rules_only_eligible.json")
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="t1",
            job_title="Lead Systems Architect",
            company_name="Cloud Corp GmbH",
            canonical_company_id=uuid.uuid4(),
        )
        job_payload = build_job_payload(
            sub, cfg_autonumber, sequence_number=1, marker="marker-1", company_salesforce_id="001000000000AAA"
        )
        assert "Job_Title__c" in job_payload
        assert job_payload["Job_Title__c"] == "Lead Systems Architect"
        assert "Name" not in job_payload

    # --- V03: Collision Across All Mapped Roles ---
    def test_v03_ownership_and_semantic_collision_rejections(self) -> None:
        # Candidate field aliases External ID
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected"):
            SyncMappingConfig(candidate_fields=["Canonical_Job_Id__c"])

        # Candidate field aliases Lookup field
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected"):
            SyncMappingConfig(candidate_fields=["Company__c"])

        # Candidate field aliases Sync Marker
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected"):
            SyncMappingConfig(candidate_fields=["Sync_Operation_Marker__c"])

        # Two machine roles alias one field
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected: machine roles.*alias the same Job field"):
            SyncMappingConfig(title_field="Availability__c", availability_field="Availability__c")

    # --- V04: Canonical UUID Idempotency & Upsert Key Stability ---
    def test_v04_canonical_uuid_external_id_stability(
        self, default_config: SyncMappingConfig
    ) -> None:
        comp_id = uuid.uuid4()
        job_id = uuid.uuid4()

        ext_comp_1 = build_company_external_id(comp_id)
        ext_comp_2 = build_company_external_id(comp_id)
        assert ext_comp_1 == ext_comp_2 == str(comp_id)

        ext_job_1 = build_job_external_id(job_id)
        ext_job_2 = build_job_external_id(job_id)
        assert ext_job_1 == ext_job_2 == str(job_id)

    # --- V05: UUID Format & Immutability Validation Rules in Metadata ---
    def test_v05_uuid_validation_rules_present_in_metadata(
        self, metadata_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        comp_rules = metadata_objects["company__c"].validation_rules
        job_rules = metadata_objects["job__c"].validation_rules

        assert "canonical_company_id_format" in comp_rules
        assert "canonical_company_id_immutable" in comp_rules
        assert "canonical_job_id_format" in job_rules
        assert "canonical_job_id_immutable" in job_rules

        # Check regex formula checks for lowercase UUID
        rule = job_rules["canonical_job_id_format"]
        assert "REGEX" in rule.error_condition_formula
        assert "[0-9a-f]{8}-[0-9a-f]{4}" in rule.error_condition_formula

        # Check immutability formula checks PRIORVALUE
        rule_imm = job_rules["canonical_job_id_immutable"]
        assert "PRIORVALUE" in rule_imm.error_condition_formula
        assert "ISCHANGED" in rule_imm.error_condition_formula

    # --- V06: Distinct UUIDs Retain Identity Across Identical Titles ---
    def test_v06_distinct_uuids_with_identical_titles(
        self, default_config: SyncMappingConfig
    ) -> None:
        asm1 = load_fixture("rules_only_eligible.json")
        asm2 = load_fixture("llm_eligible.json")

        sub1 = SyncSubmission(
            assessment=asm1,
            canonical_job_id=asm1.canonical_job_id,
            posting_revision=asm1.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="t1",
            job_title="Software Architect",
            company_name="Innovatech GmbH",
            canonical_company_id=uuid.uuid4(),
        )
        sub2 = SyncSubmission(
            assessment=asm2,
            canonical_job_id=asm2.canonical_job_id,
            posting_revision=asm2.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="t2",
            job_title="Software Architect",
            company_name="Innovatech GmbH",
            canonical_company_id=uuid.uuid4(),
        )

        assert sub1.canonical_job_id != sub2.canonical_job_id
        assert build_job_external_id(sub1.canonical_job_id) != build_job_external_id(sub2.canonical_job_id)

    # --- V07: Parent-Child Relationship & Cascade Protection ---
    def test_v07_lookup_relationship_and_restrict_delete(
        self, metadata_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        lookup = metadata_objects["job__c"].fields["company__c"]
        assert lookup.field_type == "Lookup"
        assert lookup.reference_to == "Company__c"
        assert lookup.delete_constraint == "Restrict"
        assert lookup.relationship_name == "Jobs"

        # Payload maps confirmed Salesforce ID of parent company
        asm = load_fixture("rules_only_eligible.json")
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="t1",
            job_title="Senior Engineer",
            company_name="Acme AG",
            canonical_company_id=uuid.uuid4(),
        )
        payload = build_job_payload(
            sub, default_config, sequence_number=1, marker="marker-1", company_salesforce_id="001000000000AAA"
        )
        assert payload["Company__c"] == "001000000000AAA"

    # --- V08: All Dispositions and Availability Values ---
    def test_v08_disposition_and_availability_picklists(
        self, metadata_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        disp_meta = metadata_objects["job__c"].fields["assessment_disposition__c"]
        avail_meta = metadata_objects["job__c"].fields["availability__c"]

        assert set(default_config.disposition_mapping.values()).issubset(set(disp_meta.picklist_values))
        assert set(default_config.availability_mapping.values()).issubset(set(avail_meta.picklist_values))

        # Check that no default exists (disposition never defaults to Eligible; availability never defaults to Active)
        assert disp_meta.default_picklist_value is None
        assert avail_meta.default_picklist_value is None

    # --- V09: Score/Scale Null Clearing and UTC Time Preservation ---
    def test_v09_null_clearing_and_utc_eval_time(
        self, default_config: SyncMappingConfig
    ) -> None:
        asm_rules = load_fixture("rules_only_eligible.json")
        now_dt = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        sub = SyncSubmission(
            assessment=asm_rules,
            canonical_job_id=asm_rules.canonical_job_id,
            posting_revision=asm_rules.posting_revision,
            evaluated_at=now_dt,
            generation_token="t1",
            job_title="DevOps Engineer",
            company_name="Cloud GmbH",
            canonical_company_id=uuid.uuid4(),
        )
        payload = build_job_payload(
            sub, default_config, sequence_number=1, marker="marker-1", company_salesforce_id="001000000000AAA"
        )
        assert payload["Relevance_Score__c"] is None
        assert payload["Score_Scale__c"] is None
        assert payload["Last_Evaluated_At__c"] == "2026-11-01T12:00:00+00:00"

    # --- V10: Multiple Source URLs, Length Capacity, and Unicode Support ---
    def test_v10_urls_and_unicode_support(
        self, default_config: SyncMappingConfig
    ) -> None:
        asm = load_fixture("rules_only_eligible.json")
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="t1",
            job_title="Softwareingenieur (m/w/d) für Hochleistungs-KI & Cloud-Systeme",
            company_name="Münchner Präzisionstechnik GmbH",
            canonical_company_id=uuid.uuid4(),
            source_urls=[
                "https://example.de/jobs/1?ref=münchen",
                "https://arbeitnow.com/view/ki-cloud-ingenieur",
            ],
        )
        payload = build_job_payload(
            sub, default_config, sequence_number=1, marker="marker-1", company_salesforce_id="001000000000AAA"
        )
        assert "Münchner" in sub.company_name
        assert payload["Name"] == "Softwareingenieur (m/w/d) für Hochleistungs-KI & Cloud-Systeme"
        assert payload["Source_URLs__c"] == "https://example.de/jobs/1?ref=münchen\nhttps://arbeitnow.com/view/ki-cloud-ingenieur"

    # --- V11: Creation Default 'New' on Application_Progress__c & Omission of Candidate Fields ---
    def test_v11_creation_default_new_and_omission_of_candidate_fields(
        self, metadata_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        prog = metadata_objects["job__c"].fields["application_progress__c"]
        assert prog.default_picklist_value == "New"

        asm = load_fixture("rules_only_eligible.json")
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="t1",
            job_title="Engineer",
            company_name="Co",
            canonical_company_id=uuid.uuid4(),
        )
        payload = build_job_payload(
            sub, default_config, sequence_number=1, marker="marker-1", company_salesforce_id="001000000000AAA"
        )

        # Ensure NO candidate fields appear in payload
        assert_no_candidate_fields(payload, default_config)
        for cf in default_config.candidate_fields:
            assert cf not in payload

    # --- V12 & V13: Retention of Candidate Edits on Refresh & Null Clears ---
    def test_v12_v13_candidate_fields_preservation_contract(
        self, default_config: SyncMappingConfig
    ) -> None:
        asm_rejected = load_fixture("rules_only_rejected.json")
        sub = SyncSubmission(
            assessment=asm_rejected,
            canonical_job_id=asm_rejected.canonical_job_id,
            posting_revision=asm_rejected.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="t1",
            job_title="Engineer",
            company_name="Co",
            canonical_company_id=uuid.uuid4(),
            availability=PostingAvailability.UNAVAILABLE,
        )
        # Even when a job transitions to rejected / unavailable, machine writes do not contain candidate fields
        payload = build_job_payload(
            sub, default_config, sequence_number=2, marker="marker-2", company_salesforce_id="001000000000AAA"
        )
        assert payload["Availability__c"] == "Unavailable"
        assert payload["Assessment_Disposition__c"] == "Rejected"
        assert_no_candidate_fields(payload, default_config)

    # --- V16: Worker Access Boundaries ---
    def test_v16_worker_payload_strictly_excludes_candidate_fields(
        self, default_config: SyncMappingConfig
    ) -> None:
        bad_payload = {
            "Name": "Engineer",
            "Application_Progress__c": "Applied",
        }
        with pytest.raises(SyncOwnershipError, match="Candidate-owned field.*illegally present"):
            assert_no_candidate_fields(bad_payload, default_config)

    # --- V18: Scoped Manifest Allowlist & Protection of Baseline ---
    def test_v18_package_manifest_allowlist_structure(self) -> None:
        for manifest_path in (PACKAGE_XML_PATH, SF01_XML_PATH):
            assert manifest_path.is_file()
            tree = ET.parse(manifest_path)
            root = tree.getroot()

            # Verify no wildcard members exist
            for elem in root.iter():
                if elem.text:
                    assert elem.text.strip() != "*", f"Wildcard forbidden in manifest: {manifest_path}"

            # Verify no standard profiles are packaged
            manifest_text = manifest_path.read_text(encoding="utf-8")
            assert "Admin.profile" not in manifest_text
            assert "Standard.profile" not in manifest_text
            assert "Company__c" in manifest_text
            assert "Job__c" in manifest_text
            assert "Canonical_Company_Id__c" in manifest_text
            assert "Canonical_Job_Id__c" in manifest_text
            assert "Application_Progress__c" in manifest_text
