"""Unit and structural metadata tests for Salesforce artifact review, permissions, LWC, and FlexiPage (SF-07)."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from job_automation.salesforce.metadata_parser import (
    CustomObjectMetadata,
    CustomPermissionMetadata,
    FlexiPageMetadata,
    LwcMetadata,
    PermissionSetMetadata,
    load_permission_set,
    load_salesforce_dx_custom_permissions,
    load_salesforce_dx_flexipages,
    load_salesforce_dx_lwc,
    load_salesforce_dx_objects,
    validate_sf07_metadata,
    validate_sf07_reviewer_permission_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
CUSTOM_PERMS_DIR = SF_MAIN_DIR / "customPermissions"
LWC_DIR = SF_MAIN_DIR / "lwc"
FLEXIPAGES_DIR = SF_MAIN_DIR / "flexipages"
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"
OWNERSHIP_REGISTRY_PATH = REPO_ROOT / "salesforce" / "metadata-ownership.json"


@pytest.fixture
def loaded_objects() -> dict[str, CustomObjectMetadata]:
    return load_salesforce_dx_objects(SF_OBJECTS_DIR)


@pytest.fixture
def loaded_custom_perms() -> dict[str, CustomPermissionMetadata]:
    return load_salesforce_dx_custom_permissions(CUSTOM_PERMS_DIR)


@pytest.fixture
def loaded_lwcs() -> dict[str, LwcMetadata]:
    return load_salesforce_dx_lwc(LWC_DIR)


@pytest.fixture
def loaded_flexipages() -> dict[str, FlexiPageMetadata]:
    return load_salesforce_dx_flexipages(FLEXIPAGES_DIR)


@pytest.fixture
def reviewer_permission_set() -> PermissionSetMetadata:
    return load_permission_set(PERMSETS_DIR / "Job_Document_Reviewer.permissionset-meta.xml")


class TestSF07MetadataValidation:
    def test_load_artifact_review_object_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "ja_artifact_review__c" in loaded_objects
        obj = loaded_objects["ja_artifact_review__c"]
        assert obj.label == "Artifact Review"
        assert obj.plural_label == "Artifact Reviews"
        assert obj.sharing_model == "Private"
        assert obj.name_field_type == "AutoNumber"
        assert obj.name_field_display_format == "AR-{000000}"

    def test_artifact_review_fields_and_constraints(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        obj = loaded_objects["ja_artifact_review__c"]
        assert len(obj.fields) >= 24

        # Binding_Key__c: External ID, Unique, Case-Sensitive Text(255)
        key_f = obj.fields["binding_key__c"]
        assert key_f.field_type == "Text"
        assert key_f.external_id is True
        assert key_f.unique is True
        assert key_f.case_sensitive is True
        assert key_f.length >= 255

        # Generation_Request__c: Lookup with deleteConstraint="Restrict"
        req_f = obj.fields["generation_request__c"]
        assert req_f.field_type == "Lookup"
        assert req_f.reference_to == "Generation_Request__c"
        assert req_f.delete_constraint == "Restrict"

        # Format__c: Picklist
        fmt_f = obj.fields["format__c"]
        assert fmt_f.field_type == "Picklist"

        # Content_Hash__c: Text(128)
        hash_f = obj.fields["content_hash__c"]
        assert hash_f.field_type == "Text"
        assert hash_f.length >= 128

        # Approval_Status__c: Picklist (draft, approved, superseded)
        stat_f = obj.fields["approval_status__c"]
        assert stat_f.field_type == "Picklist"

        # Review_Revision__c: Number(8, 0)
        rev_f = obj.fields["review_revision__c"]
        assert rev_f.field_type == "Number"

    def test_artifact_review_validation_rules(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        obj = loaded_objects["ja_artifact_review__c"]
        assert "immutable_binding_fields" in obj.validation_rules
        assert "approved_requires_actor_and_timestamp" in obj.validation_rules
        assert "superseded_requires_timestamp" in obj.validation_rules

    def test_load_artifact_review_event_object_metadata(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        assert "ja_artifact_review_event__c" in loaded_objects
        obj = loaded_objects["ja_artifact_review_event__c"]
        assert obj.label == "Artifact Review Event"
        assert obj.plural_label == "Artifact Review Events"
        assert obj.sharing_model == "Private"
        assert obj.name_field_type == "AutoNumber"
        assert obj.name_field_display_format == "ARE-{000000}"

    def test_artifact_review_event_fields_and_constraints(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        obj = loaded_objects["ja_artifact_review_event__c"]
        assert len(obj.fields) >= 13

        # Event_Key__c: External ID, Unique, Case-Sensitive Text(255)
        ev_key = obj.fields["event_key__c"]
        assert ev_key.field_type == "Text"
        assert ev_key.external_id is True
        assert ev_key.unique is True
        assert ev_key.case_sensitive is True

        # Artifact_Review__c: Lookup with deleteConstraint="Restrict"
        rev_lookup = obj.fields["artifact_review__c"]
        assert rev_lookup.field_type == "Lookup"
        assert rev_lookup.reference_to == "JA_Artifact_Review__c"
        assert rev_lookup.delete_constraint == "Restrict"

    def test_custom_permission_metadata(
        self, loaded_custom_perms: dict[str, CustomPermissionMetadata]
    ) -> None:
        assert "ja_review_generated_documents" in loaded_custom_perms
        perm = loaded_custom_perms["ja_review_generated_documents"]
        assert perm.label == "Review Generated Documents"

    def test_reviewer_permission_set(
        self, reviewer_permission_set: PermissionSetMetadata
    ) -> None:
        report = validate_sf07_reviewer_permission_set(reviewer_permission_set)
        assert report.compatible is True, f"Reviewer PermSet issues: {report.issues}"

        # Custom permission
        assert reviewer_permission_set.custom_permissions.get("ja_review_generated_documents") is True

        # Read-only on review objects (no create, no edit, no delete)
        for obj in ("ja_artifact_review__c", "ja_artifact_review_event__c"):
            op = reviewer_permission_set.object_permissions[obj]
            assert op.allow_read is True
            assert op.allow_create is False
            assert op.allow_edit is False
            assert op.allow_delete is False

    def test_lwc_bundle_metadata(self, loaded_lwcs: dict[str, LwcMetadata]) -> None:
        assert "jaartifactreview" in loaded_lwcs
        lwc = loaded_lwcs["jaartifactreview"]
        assert lwc.is_exposed is True
        assert "lightning__RecordPage" in lwc.targets
        assert "Generation_Request__c" in lwc.target_objects

    def test_flexipage_metadata(
        self, loaded_flexipages: dict[str, FlexiPageMetadata]
    ) -> None:
        fp_matches = [fp for k, fp in loaded_flexipages.items() if k.lower() == "ja_generation_request_review"]
        assert len(fp_matches) == 1
        fp = fp_matches[0]
        assert fp.sobject_type == "Generation_Request__c"

    def test_sf07_manifest_package(self) -> None:
        manifest_path = MANIFEST_DIR / "sf07.xml"
        assert manifest_path.exists()
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        types_map: dict[str, list[str]] = {}
        for t_elem in root.findall("{http://soap.sforce.com/2006/04/metadata}types"):
            name = t_elem.find("{http://soap.sforce.com/2006/04/metadata}name").text
            members = [m.text for m in t_elem.findall("{http://soap.sforce.com/2006/04/metadata}members")]
            types_map[name] = members

        assert "JA_Artifact_Review__c" in types_map.get("CustomObject", [])
        assert "JA_Artifact_Review_Event__c" in types_map.get("CustomObject", [])
        assert "Job_Document_Reviewer" in types_map.get("PermissionSet", [])
        assert "JA_Review_Generated_Documents" in types_map.get("CustomPermission", [])
        assert "jaArtifactReview" in types_map.get("LightningComponentBundle", [])
        assert "JA_ArtifactReviewService" in types_map.get("ApexClass", [])
        assert "JA_ArtifactRegistration" in types_map.get("ApexClass", [])

    def test_sf07_metadata_ownership_registry(self) -> None:
        reg = json.loads(OWNERSHIP_REGISTRY_PATH.read_text(encoding="utf-8"))
        po = reg["project_owned"]
        assert "JA_Artifact_Review__c" in po["CustomObject"]
        assert "JA_Artifact_Review_Event__c" in po["CustomObject"]
        assert "Job_Document_Reviewer" in po["PermissionSet"]
        assert "JA_Review_Generated_Documents" in po.get("CustomPermission", [])
        assert "jaArtifactReview" in po.get("LightningComponentBundle", [])
        assert "JA_ArtifactReviewService" in po["ApexClass"]
