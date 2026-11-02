"""Unit and contract tests for Salesforce Generation_Request__c metadata, permissions, and UI (SF-05)."""

from __future__ import annotations

import copy
from pathlib import Path
import pytest

from job_automation.generation.request_mapping import RequestFieldMapping
from job_automation.salesforce.metadata_parser import (
    CustomFieldMetadata,
    CustomObjectMetadata,
    ValidationRuleMetadata,
    load_permission_set,
    load_salesforce_dx_applications,
    load_salesforce_dx_layouts,
    load_salesforce_dx_list_views,
    load_salesforce_dx_objects,
    load_salesforce_dx_tabs,
    validate_generation_request_metadata,
    validate_generation_requester_permission_set,
    validate_worker_permission_set,
)
from job_automation.salesforce.sync_settings import load_sync_mapping_config

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
CONFIG_PATH = REPO_ROOT / "config" / "sync.example.json"


@pytest.fixture
def loaded_objects() -> dict[str, CustomObjectMetadata]:
    return load_salesforce_dx_objects(SF_OBJECTS_DIR)


@pytest.fixture
def request_mapping() -> RequestFieldMapping:
    return RequestFieldMapping()


class TestSF05MetadataValidation:
    def test_load_generation_request_object_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "generation_request__c" in loaded_objects
        obj = loaded_objects["generation_request__c"]
        assert obj.label == "Generation Request"
        assert obj.plural_label == "Generation Requests"
        assert obj.sharing_model == "Private"
        assert obj.name_field_type == "AutoNumber"
        assert obj.name_field_display_format == "GR-{000000}"

    def test_generation_request_metadata_compatibility_passes(
        self, loaded_objects: dict[str, CustomObjectMetadata], request_mapping: RequestFieldMapping
    ) -> None:
        report = validate_generation_request_metadata(loaded_objects, request_mapping)
        assert report.compatible is True, f"Metadata validation failed: {report.issues}"
        assert len(report.issues) == 0

    def test_missing_request_object_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], request_mapping: RequestFieldMapping
    ) -> None:
        bad_objs = {k: v for k, v in loaded_objects.items() if k != "generation_request__c"}
        report = validate_generation_request_metadata(bad_objs, request_mapping)
        assert report.compatible is False
        assert any("Generation Request object 'Generation_Request__c' is missing" in iss for iss in report.issues)

    def test_client_request_key_must_be_external_id_and_unique(
        self, loaded_objects: dict[str, CustomObjectMetadata], request_mapping: RequestFieldMapping
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["generation_request__c"].fields["client_request_key__c"]
        objs["generation_request__c"].fields["client_request_key__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Text",
            external_id=False,  # Bad
            unique=True,
            case_sensitive=True,
        )
        report = validate_generation_request_metadata(objs, request_mapping)
        assert report.compatible is False
        assert any("External ID" in iss for iss in report.issues)

    def test_job_lookup_must_restrict_deletion(
        self, loaded_objects: dict[str, CustomObjectMetadata], request_mapping: RequestFieldMapping
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["generation_request__c"].fields["job__c"]
        objs["generation_request__c"].fields["job__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Lookup",
            reference_to="Job__c",
            delete_constraint="SetNull",  # Bad
        )
        report = validate_generation_request_metadata(objs, request_mapping)
        assert report.compatible is False
        assert any("deleteConstraint must be 'Restrict'" in iss for iss in report.issues)

    def test_language_picklist_default_must_be_de(
        self, loaded_objects: dict[str, CustomObjectMetadata], request_mapping: RequestFieldMapping
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["generation_request__c"].fields["language__c"]
        objs["generation_request__c"].fields["language__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Picklist",
            picklist_values=orig_f.picklist_values,
            default_picklist_value="en",  # Bad default
            restricted_picklist=True,
        )
        report = validate_generation_request_metadata(objs, request_mapping)
        assert report.compatible is False
        assert any("default value must be 'de'" in iss for iss in report.issues)

    def test_missing_validation_rule_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], request_mapping: RequestFieldMapping
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        del objs["generation_request__c"].validation_rules["claim_requires_claimed_at_and_versions"]
        report = validate_generation_request_metadata(objs, request_mapping)
        assert report.compatible is False
        assert any("Claim_Requires_Claimed_At_And_Versions" in iss for iss in report.issues)


class TestSF05PermissionsValidation:
    def test_job_generation_requester_permission_set(
        self, request_mapping: RequestFieldMapping
    ) -> None:
        ps_path = PERMSETS_DIR / "Job_Generation_Requester.permissionset-meta.xml"
        assert ps_path.is_file()
        ps = load_permission_set(ps_path)
        report = validate_generation_requester_permission_set(ps, request_mapping)
        assert report.compatible is True, f"Requester PermSet issues: {report.issues}"

        # Requester cannot edit worker-managed fields
        assert ps.field_permissions["generation_request__c.status__c"].editable is False
        assert ps.field_permissions["generation_request__c.worker_claimed_at__c"].editable is False
        assert ps.field_permissions["generation_request__c.completed_at__c"].editable is False
        assert ps.field_permissions["generation_request__c.result_artifact_ref__c"].editable is False
        assert ps.field_permissions["generation_request__c.error_reason__c"].editable is False

        # Requester CAN create requests and write creation inputs
        assert ps.object_permissions["generation_request__c"].allow_create is True
        assert ps.field_permissions["generation_request__c.job__c"].editable is True
        assert ps.field_permissions["generation_request__c.document_type__c"].editable is True
        assert ps.field_permissions["generation_request__c.allow_unavailable_job__c"].editable is True

    def test_worker_permission_set_supports_generation_requests(self) -> None:
        ps_path = PERMSETS_DIR / "Job_Automation_Worker.permissionset-meta.xml"
        ps = load_permission_set(ps_path)
        cfg = load_sync_mapping_config(CONFIG_PATH)
        report = validate_worker_permission_set(ps, cfg)
        assert report.compatible is True, f"Worker PermSet issues: {report.issues}"

        # Worker cannot create or delete requests
        assert ps.object_permissions["generation_request__c"].allow_create is False
        assert ps.object_permissions["generation_request__c"].allow_delete is False
        assert ps.object_permissions["generation_request__c"].allow_edit is True
        assert ps.object_permissions["generation_request__c"].allow_read is True

        # Worker cannot edit candidate inputs
        assert ps.field_permissions["generation_request__c.job__c"].editable is False
        assert ps.field_permissions["generation_request__c.document_type__c"].editable is False
        assert ps.field_permissions["generation_request__c.allow_unavailable_job__c"].editable is False

        # Worker CAN edit status, timestamps, frozen versions, result, and error
        assert ps.field_permissions["generation_request__c.status__c"].editable is True
        assert ps.field_permissions["generation_request__c.worker_claimed_at__c"].editable is True
        assert ps.field_permissions["generation_request__c.completed_at__c"].editable is True
        assert ps.field_permissions["generation_request__c.frozen_posting_revision__c"].editable is True
        assert ps.field_permissions["generation_request__c.result_artifact_ref__c"].editable is True


class TestSF05UIInspectionMetadata:
    def test_generation_request_list_views(self) -> None:
        views = load_salesforce_dx_list_views(SF_OBJECTS_DIR / "Generation_Request__c")
        expected_views = {"All_Requests", "In_Progress", "Failed_Requests", "Ready_Requests"}
        assert expected_views.issubset(set(views.keys()))
        for vname in expected_views:
            v = views[vname]
            assert v.filter_scope == "Everything"
            assert "NAME" in v.columns
            assert "Job__c" in v.columns
            assert "Status__c" in v.columns

    def test_generation_request_detail_layout(self) -> None:
        layouts = load_salesforce_dx_layouts(SF_MAIN_DIR / "layouts")
        assert "Generation_Request__c-JA Generation Request Detail" in layouts
        layout = layouts["Generation_Request__c-JA Generation Request Detail"]
        section_labels = {s.label for s in layout.sections}
        assert "Request Overview" in section_labels
        assert "Status and Execution" in section_labels
        assert "Frozen Input Versions" in section_labels
        assert "Delivered Artifacts" in section_labels
        assert "Diagnostic Information" in section_labels

    def test_custom_tab_and_app_navigation(self) -> None:
        tabs = load_salesforce_dx_tabs(SF_MAIN_DIR / "tabs")
        assert "Generation_Request__c" in tabs

        apps = load_salesforce_dx_applications(SF_MAIN_DIR / "applications")
        assert "Job_Tracker" in apps
        assert "Generation_Request__c" in apps["Job_Tracker"].tabs

    def test_job_layout_contains_requests_related_list(self) -> None:
        layouts = load_salesforce_dx_layouts(SF_MAIN_DIR / "layouts")
        jl = layouts["Job__c-JA Candidate Tracking"]
        # Parse XML directly to check relatedLists
        xml_path = SF_MAIN_DIR / "layouts" / "Job__c-JA Candidate Tracking.layout-meta.xml"
        content = xml_path.read_text(encoding="utf-8")
        assert "Generation_Request__c.Job__c" in content

