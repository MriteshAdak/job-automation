"""Unit and structural metadata tests for Salesforce generation actions, flows, receipts, and permissions (SF-06)."""

from __future__ import annotations

import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from job_automation.salesforce.metadata_parser import (
    CustomObjectMetadata,
    FlowMetadata,
    PermissionSetMetadata,
    QuickActionMetadata,
    load_permission_set,
    load_salesforce_dx_custom_metadata,
    load_salesforce_dx_flows,
    load_salesforce_dx_layouts,
    load_salesforce_dx_objects,
    load_salesforce_dx_quick_actions,
    validate_sf06_actions_permission_set,
    validate_sf06_metadata,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
FLOWS_DIR = SF_MAIN_DIR / "flows"
QUICKACTIONS_DIR = SF_MAIN_DIR / "quickActions"
CUSTOM_METADATA_DIR = SF_MAIN_DIR / "customMetadata"
LAYOUTS_DIR = SF_MAIN_DIR / "layouts"
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"


@pytest.fixture
def loaded_objects() -> dict[str, CustomObjectMetadata]:
    return load_salesforce_dx_objects(SF_OBJECTS_DIR)


@pytest.fixture
def loaded_flows() -> dict[str, FlowMetadata]:
    return load_salesforce_dx_flows(FLOWS_DIR)


@pytest.fixture
def loaded_quick_actions() -> dict[str, QuickActionMetadata]:
    return load_salesforce_dx_quick_actions(QUICKACTIONS_DIR)


@pytest.fixture
def loaded_options() -> dict[str, Any]:
    return load_salesforce_dx_custom_metadata(CUSTOM_METADATA_DIR)


@pytest.fixture
def actions_permission_set() -> PermissionSetMetadata:
    return load_permission_set(PERMSETS_DIR / "Job_Generation_Actions.permissionset-meta.xml")


class TestSF06MetadataValidation:
    def test_load_submission_receipt_object_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "ja_generation_submission__c" in loaded_objects
        obj = loaded_objects["ja_generation_submission__c"]
        assert obj.label == "Generation Submission"
        assert obj.plural_label == "Generation Submissions"
        assert obj.sharing_model == "Private"
        assert obj.name_field_type == "AutoNumber"
        assert obj.name_field_display_format == "GS-{000000}"

    def test_submission_receipt_fields_and_constraints(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        obj = loaded_objects["ja_generation_submission__c"]
        assert len(obj.fields) >= 5

        # Submission_Key__c: External ID, Unique, Case-Sensitive Text(255)
        key_f = obj.fields["submission_key__c"]
        assert key_f.field_type == "Text"
        assert key_f.external_id is True
        assert key_f.unique is True
        assert key_f.case_sensitive is True
        assert key_f.length >= 255

        # Request__c: Lookup with deleteConstraint="Restrict"
        req_f = obj.fields["request__c"]
        assert req_f.field_type == "Lookup"
        assert req_f.reference_to == "Generation_Request__c"
        assert req_f.delete_constraint == "Restrict"

        # Intent_Payload__c: LongTextArea
        payload_f = obj.fields["intent_payload__c"]
        assert payload_f.field_type == "LongTextArea"
        assert payload_f.length >= 32768

    def test_load_generation_option_mdt_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "ja_generation_option__mdt" in loaded_objects
        obj = loaded_objects["ja_generation_option__mdt"]
        assert obj.label == "Generation Option"
        assert obj.plural_label == "Generation Options"
        assert obj.visibility == "Public"

        assert "template_id__c" in obj.fields
        assert "document_type__c" in obj.fields
        assert "allowed_languages__c" in obj.fields
        assert "is_enabled__c" in obj.fields
        assert "catalog_version__c" in obj.fields

    def test_sf06_metadata_compatibility_passes(
        self,
        loaded_objects: dict[str, CustomObjectMetadata],
        loaded_flows: dict[str, FlowMetadata],
        loaded_quick_actions: dict[str, QuickActionMetadata],
        loaded_options: dict[str, Any],
    ) -> None:
        report = validate_sf06_metadata(
            loaded_objects, loaded_flows, loaded_quick_actions, loaded_options
        )
        assert report.compatible is True, f"Metadata validation failed: {report.issues}"
        assert len(report.issues) == 0

    def test_screen_flows_structure_and_action_bindings(
        self, loaded_flows: dict[str, FlowMetadata]
    ) -> None:
        assert "ja_generate_cv" in loaded_flows
        cv_flow = loaded_flows["ja_generate_cv"]
        assert cv_flow.status == "Active"
        assert cv_flow.process_type == "Flow"
        assert "recordId" in cv_flow.variables
        assert "Submit_Generation_Request" in cv_flow.action_calls
        assert "Screen_CV_Options" in cv_flow.screens
        assert "Screen_CV_Result" in cv_flow.screens

        assert "ja_generate_cover_letter" in loaded_flows
        letter_flow = loaded_flows["ja_generate_cover_letter"]
        assert letter_flow.status == "Active"
        assert letter_flow.process_type == "Flow"
        assert "recordId" in letter_flow.variables
        assert "Submit_Generation_Request" in letter_flow.action_calls
        assert "Screen_Letter_Options" in letter_flow.screens
        assert "Screen_Letter_Result" in letter_flow.screens

    def test_quick_actions_bind_to_flows(
        self, loaded_quick_actions: dict[str, QuickActionMetadata]
    ) -> None:
        assert "job__c.ja_generate_cv" in loaded_quick_actions
        qa_cv = loaded_quick_actions["job__c.ja_generate_cv"]
        assert qa_cv.action_type == "Flow"
        assert qa_cv.flow_definition == "JA_Generate_CV"
        assert qa_cv.label == "Generate CV"

        assert "job__c.ja_generate_cover_letter" in loaded_quick_actions
        qa_letter = loaded_quick_actions["job__c.ja_generate_cover_letter"]
        assert qa_letter.action_type == "Flow"
        assert qa_letter.flow_definition == "JA_Generate_Cover_Letter"
        assert qa_letter.label == "Generate Cover Letter"

    def test_job_layout_contains_generation_quick_actions(self) -> None:
        layout_path = LAYOUTS_DIR / "Job__c-JA Candidate Tracking.layout-meta.xml"
        tree = ET.parse(layout_path)
        root = tree.getroot()

        action_names: list[str] = []
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "platformActionList":
                for item in child:
                    item_tag = item.tag.split("}")[-1] if "}" in item.tag else item.tag
                    if item_tag == "platformActionListItems":
                        for sub in item:
                            sub_tag = sub.tag.split("}")[-1] if "}" in sub.tag else sub.tag
                            if sub_tag == "actionName" and sub.text:
                                action_names.append(sub.text)

        assert "Job__c.JA_Generate_CV" in action_names
        assert "Job__c.JA_Generate_Cover_Letter" in action_names

    def test_actions_permission_set_validation(
        self, actions_permission_set: PermissionSetMetadata
    ) -> None:
        report = validate_sf06_actions_permission_set(actions_permission_set)
        assert report.compatible is True, f"Permission set validation failed: {report.issues}"

        # Apex class access
        assert "ja_generationsubmit" in actions_permission_set.class_accesses
        assert actions_permission_set.class_accesses["ja_generationsubmit"] is True

        # Flow accesses
        assert actions_permission_set.flow_accesses.get("ja_generate_cv") is True
        assert actions_permission_set.flow_accesses.get("ja_generate_cover_letter") is True

        # Candidate has Read/Create on JA_Generation_Submission__c, no Edit, no Delete
        sub_op = actions_permission_set.object_permissions["ja_generation_submission__c"]
        assert sub_op.allow_create is True
        assert sub_op.allow_read is True
        assert sub_op.allow_edit is False
        assert sub_op.allow_delete is False

        # Candidate has Read/Create on Generation_Request__c, no Edit, no Delete
        req_op = actions_permission_set.object_permissions["generation_request__c"]
        assert req_op.allow_create is True
        assert req_op.allow_read is True
        assert req_op.allow_edit is False
        assert req_op.allow_delete is False

    def test_scoped_manifest_sf06_covers_all_components(self) -> None:
        manifest_path = MANIFEST_DIR / "sf06.xml"
        assert manifest_path.is_file()

        tree = ET.parse(manifest_path)
        root = tree.getroot()

        types_dict: dict[str, set[str]] = {}
        for types_elem in root.findall("{http://soap.sforce.com/2006/04/metadata}types"):
            name_elem = types_elem.find("{http://soap.sforce.com/2006/04/metadata}name")
            if name_elem is not None and name_elem.text:
                type_name = name_elem.text
                members = {
                    m.text
                    for m in types_elem.findall("{http://soap.sforce.com/2006/04/metadata}members")
                    if m.text
                }
                types_dict[type_name] = members

        assert "CustomObject" in types_dict
        assert "JA_Generation_Submission__c" in types_dict["CustomObject"]
        assert "JA_Generation_Option__mdt" in types_dict["CustomObject"]

        assert "CustomField" in types_dict
        assert "JA_Generation_Submission__c.Submission_Key__c" in types_dict["CustomField"]
        assert "JA_Generation_Option__mdt.Template_Id__c" in types_dict["CustomField"]

        assert "ApexClass" in types_dict
        assert "JA_GenerationSubmit" in types_dict["ApexClass"]
        assert "JA_GenerationSubmitTest" in types_dict["ApexClass"]

        assert "Flow" in types_dict
        assert "JA_Generate_CV" in types_dict["Flow"]
        assert "JA_Generate_Cover_Letter" in types_dict["Flow"]

        assert "QuickAction" in types_dict
        assert "Job__c.JA_Generate_CV" in types_dict["QuickAction"]
        assert "Job__c.JA_Generate_Cover_Letter" in types_dict["QuickAction"]

        assert "PermissionSet" in types_dict
        assert "Job_Generation_Actions" in types_dict["PermissionSet"]

