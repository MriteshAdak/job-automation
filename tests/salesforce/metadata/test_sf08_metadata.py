"""Unit and structural metadata tests for Salesforce generation notifications, Flows, config, and ledger (SF-08)."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from job_automation.salesforce.metadata_parser import (
    CustomNotificationTypeMetadata,
    CustomObjectMetadata,
    CustomPermissionMetadata,
    FlowMetadata,
    PermissionSetMetadata,
    load_permission_set,
    load_salesforce_dx_custom_permissions,
    load_salesforce_dx_flows,
    load_salesforce_dx_notification_types,
    load_salesforce_dx_objects,
    validate_sf08_admin_permission_set,
    validate_sf08_metadata,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
CUSTOM_PERMS_DIR = SF_MAIN_DIR / "customPermissions"
FLOWS_DIR = SF_MAIN_DIR / "flows"
NOTIF_TYPES_DIR = SF_MAIN_DIR / "notificationtypes"
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"
OWNERSHIP_REGISTRY_PATH = REPO_ROOT / "salesforce" / "metadata-ownership.json"


@pytest.fixture
def loaded_objects() -> dict[str, CustomObjectMetadata]:
    return load_salesforce_dx_objects(SF_OBJECTS_DIR)


@pytest.fixture
def loaded_custom_perms() -> dict[str, CustomPermissionMetadata]:
    return load_salesforce_dx_custom_permissions(CUSTOM_PERMS_DIR)


@pytest.fixture
def loaded_flows() -> dict[str, FlowMetadata]:
    return load_salesforce_dx_flows(FLOWS_DIR)


@pytest.fixture
def loaded_notif_types() -> dict[str, CustomNotificationTypeMetadata]:
    return load_salesforce_dx_notification_types(NOTIF_TYPES_DIR)


@pytest.fixture
def admin_permission_set() -> PermissionSetMetadata:
    return load_permission_set(PERMSETS_DIR / "Job_Notification_Administrator.permissionset-meta.xml")


@pytest.fixture
def reviewer_permission_set() -> PermissionSetMetadata:
    return load_permission_set(PERMSETS_DIR / "Job_Document_Reviewer.permissionset-meta.xml")


class TestSF08MetadataValidation:
    def test_load_notification_types(
        self, loaded_notif_types: dict[str, CustomNotificationTypeMetadata]
    ) -> None:
        assert "ja_draft_ready" in loaded_notif_types
        ready_type = loaded_notif_types["ja_draft_ready"]
        assert ready_type.desktop is True
        assert ready_type.mobile is False
        assert "ready for candidate review" in (ready_type.description or "").lower()

        assert "ja_request_action_required" in loaded_notif_types
        action_type = loaded_notif_types["ja_request_action_required"]
        assert action_type.desktop is True
        assert action_type.mobile is False
        assert "action" in (action_type.description or "").lower()

    def test_load_notification_config_object_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "ja_notification_config__c" in loaded_objects
        obj = loaded_objects["ja_notification_config__c"]
        assert obj.label == "Notification Config"
        assert obj.plural_label == "Notification Configs"
        assert obj.sharing_model == "Private"
        assert obj.name_field_type == "AutoNumber"
        assert obj.name_field_display_format == "NC-{000000}"

        # Check required fields
        assert "is_enabled__c" in obj.fields
        assert obj.fields["is_enabled__c"].field_type == "Checkbox"

        assert "candidate_user__c" in obj.fields
        cand_user = obj.fields["candidate_user__c"]
        assert cand_user.field_type == "Lookup"
        assert cand_user.reference_to == "User"
        assert cand_user.delete_constraint == "Restrict"

        assert "preferred_language__c" in obj.fields
        lang_fld = obj.fields["preferred_language__c"]
        assert lang_fld.field_type == "Picklist"
        assert "en" in lang_fld.picklist_values
        assert "de" in lang_fld.picklist_values

        assert "org_key__c" in obj.fields
        ok_fld = obj.fields["org_key__c"]
        assert ok_fld.external_id is True
        assert ok_fld.unique is True
        assert ok_fld.case_sensitive is True

        assert "enabled_requires_candidate" in obj.validation_rules

    def test_load_request_notification_ledger_object_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "ja_request_notification__c" in loaded_objects
        obj = loaded_objects["ja_request_notification__c"]
        assert obj.label == "Request Notification"
        assert obj.plural_label == "Request Notifications"
        assert obj.sharing_model == "Private"
        assert obj.name_field_type == "AutoNumber"
        assert obj.name_field_display_format == "NOTIF-{000000}"

        # Key fields
        assert "alert_key__c" in obj.fields
        ak = obj.fields["alert_key__c"]
        assert ak.field_type == "Text"
        assert ak.external_id is True
        assert ak.unique is True
        assert ak.case_sensitive is True
        assert ak.required is True

        assert "generation_request__c" in obj.fields
        gr = obj.fields["generation_request__c"]
        assert gr.field_type == "Lookup"
        assert gr.reference_to == "Generation_Request__c"
        assert gr.delete_constraint == "Restrict"

        assert "recipient_user__c" in obj.fields
        ru = obj.fields["recipient_user__c"]
        assert ru.field_type == "Lookup"
        assert ru.reference_to == "User"
        assert ru.delete_constraint == "Restrict"

        assert "status__c" in obj.fields
        st = obj.fields["status__c"]
        assert st.field_type == "Picklist"
        expected_statuses = {"Pending", "Blocked", "Dispatching", "Accepted", "Retry_Wait", "Uncertain", "Suppressed", "Dead_Letter"}
        assert expected_statuses.issubset(set(st.picklist_values))

        # Validation rules
        assert "immutable_alert_key" in obj.validation_rules
        assert "accepted_requires_timestamp" in obj.validation_rules
        assert "uncertain_requires_reason" in obj.validation_rules

    def test_load_flows_metadata(
        self, loaded_flows: dict[str, FlowMetadata]
    ) -> None:
        assert "ja_request_notification_observe" in loaded_flows
        obs_flow = loaded_flows["ja_request_notification_observe"]
        assert obs_flow.process_type == "AutoLaunchedFlow"
        assert obs_flow.status == "Draft"
        assert "Admit_Request_Notification" in obs_flow.action_calls

        assert "ja_request_notification_dispatch" in loaded_flows
        disp_flow = loaded_flows["ja_request_notification_dispatch"]
        assert disp_flow.process_type == "AutoLaunchedFlow"
        assert disp_flow.status == "Draft"
        assert "Dispatch_Request_Notification" in disp_flow.action_calls

    def test_load_custom_permissions(
        self, loaded_custom_perms: dict[str, CustomPermissionMetadata]
    ) -> None:
        assert "ja_administer_notifications" in loaded_custom_perms
        cp = loaded_custom_perms["ja_administer_notifications"]
        assert "administration" in (cp.description or "").lower() or "administer" in cp.label.lower()

    def test_admin_permission_set(
        self, admin_permission_set: PermissionSetMetadata
    ) -> None:
        report = validate_sf08_admin_permission_set(admin_permission_set)
        assert report.compatible is True, f"Admin perm set issues: {report.issues}"

        # Custom permission
        assert admin_permission_set.custom_permissions.get("ja_administer_notifications") is True

        # Apex class accesses
        for cls_name in ("ja_requestnotificationadmission", "ja_requestnotificationdispatcher", "ja_requestnotificationrecovery"):
            assert admin_permission_set.class_accesses.get(cls_name) is True

        # Flow accesses
        for fl_name in ("ja_request_notification_observe", "ja_request_notification_dispatch"):
            assert admin_permission_set.flow_accesses.get(fl_name) is True

        # Full CRUD on notification objects
        for obj_name in ("ja_notification_config__c", "ja_request_notification__c"):
            op = admin_permission_set.object_permissions[obj_name]
            assert op.allow_read is True
            assert op.allow_create is True
            assert op.allow_edit is True
            assert op.allow_delete is True

    def test_reviewer_permission_set_has_read_only_notifications(
        self, reviewer_permission_set: PermissionSetMetadata
    ) -> None:
        assert "ja_request_notification__c" in reviewer_permission_set.object_permissions
        op = reviewer_permission_set.object_permissions["ja_request_notification__c"]
        assert op.allow_read is True
        assert op.allow_create is False
        assert op.allow_edit is False
        assert op.allow_delete is False

    def test_sf08_metadata_compatibility_passes(
        self,
        loaded_objects: dict[str, CustomObjectMetadata],
        loaded_flows: dict[str, FlowMetadata],
        loaded_notif_types: dict[str, CustomNotificationTypeMetadata],
        loaded_custom_perms: dict[str, CustomPermissionMetadata],
    ) -> None:
        perm_sets = {
            "job_notification_administrator": load_permission_set(
                PERMSETS_DIR / "Job_Notification_Administrator.permissionset-meta.xml"
            )
        }
        report = validate_sf08_metadata(
            objects=loaded_objects,
            perm_sets=perm_sets,
            flows=loaded_flows,
            notif_types=loaded_notif_types,
            custom_perms=loaded_custom_perms,
        )
        assert report.compatible is True, f"SF-08 validation issues: {report.issues}"
        assert len(report.issues) == 0

    def test_sf08_manifest_and_registry(self) -> None:
        sf08_manifest = MANIFEST_DIR / "sf08.xml"
        assert sf08_manifest.exists()
        tree = ET.parse(sf08_manifest)
        root = tree.getroot()
        ns = "{http://soap.sforce.com/2006/04/metadata}"

        manifest_members: dict[str, set[str]] = {}
        for type_elem in root.findall(f"{ns}types"):
            name_el = type_elem.find(f"{ns}name")
            if name_el is not None and name_el.text:
                t_name = name_el.text
                manifest_members[t_name] = {
                    m.text for m in type_elem.findall(f"{ns}members") if m.text
                }

        assert "CustomNotificationType" in manifest_members
        assert "JA_Draft_Ready" in manifest_members["CustomNotificationType"]
        assert "JA_Request_Action_Required" in manifest_members["CustomNotificationType"]

        assert "CustomObject" in manifest_members
        assert "JA_Notification_Config__c" in manifest_members["CustomObject"]
        assert "JA_Request_Notification__c" in manifest_members["CustomObject"]

        assert "Flow" in manifest_members
        assert "JA_Request_Notification_Observe" in manifest_members["Flow"]
        assert "JA_Request_Notification_Dispatch" in manifest_members["Flow"]

        assert "PermissionSet" in manifest_members
        assert "Job_Notification_Administrator" in manifest_members["PermissionSet"]

        # Check ownership registry
        with open(OWNERSHIP_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)

        project_owned = registry["project_owned"]
        assert "CustomNotificationType" in project_owned
        assert "JA_Draft_Ready" in project_owned["CustomNotificationType"]
        assert "JA_Notification_Config__c" in project_owned["CustomObject"]
        assert "JA_Request_Notification__c" in project_owned["CustomObject"]
        assert "JA_Request_Notification_Observe" in project_owned["Flow"]

