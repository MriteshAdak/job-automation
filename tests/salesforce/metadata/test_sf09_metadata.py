"""Unit and structural metadata tests for Salesforce run summary target, flows, and permissions (SF-09)."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from job_automation.salesforce.metadata_parser import (
    CustomNotificationTypeMetadata,
    CustomObjectMetadata,
    FlowMetadata,
    PermissionSetMetadata,
    load_permission_set,
    load_salesforce_dx_flows,
    load_salesforce_dx_notification_types,
    load_salesforce_dx_objects,
    validate_sf09_admin_permission_set,
    validate_sf09_metadata,
    validate_sf09_reader_permission_set,
    validate_sf09_worker_permission_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
FLOWS_DIR = SF_MAIN_DIR / "flows"
NOTIF_TYPES_DIR = SF_MAIN_DIR / "notificationtypes"
TABS_DIR = SF_MAIN_DIR / "tabs"
LAYOUTS_DIR = SF_MAIN_DIR / "layouts"
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"
OWNERSHIP_REGISTRY_PATH = REPO_ROOT / "salesforce" / "metadata-ownership.json"


@pytest.fixture
def loaded_objects() -> dict[str, CustomObjectMetadata]:
    return load_salesforce_dx_objects(SF_OBJECTS_DIR)


@pytest.fixture
def loaded_flows() -> dict[str, FlowMetadata]:
    return load_salesforce_dx_flows(FLOWS_DIR)


@pytest.fixture
def loaded_notif_types() -> dict[str, CustomNotificationTypeMetadata]:
    return load_salesforce_dx_notification_types(NOTIF_TYPES_DIR)


@pytest.fixture
def worker_permission_set() -> PermissionSetMetadata:
    return load_permission_set(PERMSETS_DIR / "Job_Summary_Worker.permissionset-meta.xml")


@pytest.fixture
def reader_permission_set() -> PermissionSetMetadata:
    return load_permission_set(PERMSETS_DIR / "Job_Summary_Reader.permissionset-meta.xml")


@pytest.fixture
def admin_permission_set() -> PermissionSetMetadata:
    return load_permission_set(PERMSETS_DIR / "Job_Summary_Administrator.permissionset-meta.xml")


class TestSF09MetadataValidation:
    def test_load_notification_type(
        self, loaded_notif_types: dict[str, CustomNotificationTypeMetadata]
    ) -> None:
        assert "ja_run_completed" in loaded_notif_types
        nt = loaded_notif_types["ja_run_completed"]
        assert nt.desktop is True
        assert nt.mobile is False
        assert "pipeline run completes" in (nt.description or "").lower()

    def test_load_run_summary_object_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "run_summary__c" in loaded_objects
        obj = loaded_objects["run_summary__c"]
        assert obj.label == "Run Summary"
        assert obj.plural_label == "Run Summaries"
        assert obj.sharing_model == "Private"
        assert obj.name_field_type == "Text"

        # 1. Unique External IDs
        assert "run_id__c" in obj.fields
        run_id_fld = obj.fields["run_id__c"]
        assert run_id_fld.field_type == "Text"
        assert run_id_fld.external_id is True
        assert run_id_fld.unique is True
        assert run_id_fld.required is True

        assert "first_completion_key__c" in obj.fields
        comp_key_fld = obj.fields["first_completion_key__c"]
        assert comp_key_fld.field_type == "Text"
        assert comp_key_fld.external_id is True
        assert comp_key_fld.unique is True
        assert comp_key_fld.required is True

        # 2. Timing and duration
        assert "start_time__c" in obj.fields
        assert obj.fields["start_time__c"].field_type == "DateTime"
        assert "end_time__c" in obj.fields
        assert obj.fields["end_time__c"].field_type == "DateTime"
        assert "duration_seconds__c" in obj.fields
        assert obj.fields["duration_seconds__c"].field_type == "Number"

        # 3. Status picklists
        assert "pipeline_status__c" in obj.fields
        ps_fld = obj.fields["pipeline_status__c"]
        assert ps_fld.field_type == "Picklist"
        assert set(ps_fld.picklist_values) == {"success", "partial", "failed"}

        assert "first_status__c" in obj.fields
        fs_fld = obj.fields["first_status__c"]
        assert fs_fld.field_type == "Picklist"
        assert set(fs_fld.picklist_values) == {"success", "partial", "failed"}

        assert "coverage_status__c" in obj.fields
        cov_fld = obj.fields["coverage_status__c"]
        assert cov_fld.field_type == "Picklist"
        assert set(cov_fld.picklist_values) == {"complete", "partial", "unavailable"}

        assert "notification_status__c" in obj.fields
        notif_fld = obj.fields["notification_status__c"]
        assert notif_fld.field_type == "Picklist"
        assert set(notif_fld.picklist_values) == {
            "none", "pending", "dispatching", "confirmed", "failed", "unknown", "suppressed"
        }

        # 4. Lookup to User
        assert "notification_recipient__c" in obj.fields
        recip_fld = obj.fields["notification_recipient__c"]
        assert recip_fld.field_type == "Lookup"
        assert recip_fld.reference_to == "User"

        # 5. Core counters
        for cnt in (
            "source_postings_count__c",
            "canonical_jobs_new__c",
            "canonical_jobs_updated__c",
            "canonical_jobs_duplicate__c",
            "eligible_count__c",
            "review_count__c",
            "rejected_count__c",
            "sync_succeeded__c",
            "sync_failed__c",
            "quarantined_count__c",
            "revision__c",
            "notification_attempt_count__c",
        ):
            assert cnt in obj.fields
            assert obj.fields[cnt].field_type == "Number"

        # 6. Immutable snapshots & server markers
        assert "completion_recorded_at__c" in obj.fields
        assert obj.fields["completion_recorded_at__c"].field_type == "DateTime"
        assert "first_completed_at__c" in obj.fields
        assert obj.fields["first_completed_at__c"].field_type == "DateTime"
        assert "first_headline__c" in obj.fields
        assert obj.fields["first_headline__c"].field_type == "Text"
        assert "first_summary_text__c" in obj.fields
        assert obj.fields["first_summary_text__c"].field_type == "LongTextArea"
        assert "notification_claim_id__c" in obj.fields
        assert obj.fields["notification_claim_id__c"].field_type == "Text"
        assert "notification_receipt_id__c" in obj.fields
        assert obj.fields["notification_receipt_id__c"].field_type == "Text"

        # 7. Validation rules
        for vr in (
            "immutable_run_id",
            "immutable_completion_key",
            "valid_duration",
            "end_not_before_start",
            "confirmed_requires_receipt",
            "unknown_requires_code",
        ):
            assert vr in obj.validation_rules

    def test_load_completion_flow_metadata(
        self, loaded_flows: dict[str, FlowMetadata]
    ) -> None:
        assert "ja_run_summary_completion" in loaded_flows
        fl = loaded_flows["ja_run_summary_completion"]
        assert fl.process_type == "AutoLaunchedFlow"
        assert fl.status == "Draft"

    def test_validate_sf09_metadata_compatibility(
        self,
        loaded_objects: dict[str, CustomObjectMetadata],
        loaded_flows: dict[str, FlowMetadata],
        loaded_notif_types: dict[str, CustomNotificationTypeMetadata],
    ) -> None:
        report = validate_sf09_metadata(loaded_objects, loaded_flows, loaded_notif_types)
        assert report.compatible is True, f"Metadata issues: {report.issues}"

    def test_worker_permission_set(
        self, worker_permission_set: PermissionSetMetadata
    ) -> None:
        report = validate_sf09_worker_permission_set(worker_permission_set)
        assert report.compatible is True, f"Worker permission issues: {report.issues}"

        op = worker_permission_set.object_permissions["run_summary__c"]
        assert op.allow_read is True
        assert op.allow_create is True
        assert op.allow_edit is True
        assert op.allow_delete is False
        assert op.modify_all_records is False
        assert op.view_all_records is False

    def test_reader_permission_set(
        self, reader_permission_set: PermissionSetMetadata
    ) -> None:
        report = validate_sf09_reader_permission_set(reader_permission_set)
        assert report.compatible is True, f"Reader permission issues: {report.issues}"

        op = reader_permission_set.object_permissions["run_summary__c"]
        assert op.allow_read is True
        assert op.allow_create is False
        assert op.allow_edit is False
        assert op.allow_delete is False

    def test_admin_permission_set(
        self, admin_permission_set: PermissionSetMetadata
    ) -> None:
        report = validate_sf09_admin_permission_set(admin_permission_set)
        assert report.compatible is True, f"Admin permission issues: {report.issues}"

        assert admin_permission_set.class_accesses.get("ja_runsummaryrecovery") is True

    def test_manifest_and_ownership(self) -> None:
        # Check sf09.xml manifest
        sf09_manifest = MANIFEST_DIR / "sf09.xml"
        assert sf09_manifest.exists()
        tree = ET.parse(sf09_manifest)
        root = tree.getroot()
        ns = {"ns": "http://soap.sforce.com/2006/04/metadata"}
        members = [elem.text for elem in root.findall(".//ns:members", ns)]
        assert "Run_Summary__c" in members
        assert "JA_Run_Completed" in members
        assert "JA_Run_Summary_Completion" in members
        assert "Job_Summary_Worker" in members

        # Check metadata-ownership.json
        with open(OWNERSHIP_REGISTRY_PATH, "r", encoding="utf-8") as f:
            reg = json.load(f)
        po = reg["project_owned"]
        assert "Run_Summary__c" in po["CustomObject"]
        assert "Run_Summary__c.Run_Id__c" in po["CustomField"]
        assert "JA_Run_Completed" in po["CustomNotificationType"]
        assert "JA_Run_Summary_Completion" in po["Flow"]
        assert "Job_Summary_Worker" in po["PermissionSet"]

    def test_custom_tab_and_layout_files(self) -> None:
        tab_file = TABS_DIR / "Run_Summary__c.tab-meta.xml"
        assert tab_file.exists()

        layout_file = LAYOUTS_DIR / "Run_Summary__c-Run Summary Layout.layout-meta.xml"
        assert layout_file.exists()
        layout_tree = ET.parse(layout_file)
        assert layout_tree.getroot().tag.endswith("Layout")

