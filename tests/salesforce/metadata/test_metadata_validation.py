"""Tests for Salesforce metadata parsing and compatibility validation (SF-01)."""

from __future__ import annotations

import copy
from pathlib import Path
import pytest

from job_automation.salesforce.metadata_parser import (
    CustomFieldMetadata,
    CustomObjectMetadata,
    load_salesforce_dx_objects,
    validate_metadata_compatibility,
)
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_OBJECTS_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default" / "objects"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "sync.example.json"
AUTONUMBER_CONFIG_PATH = REPO_ROOT / "config" / "sync.autonumber.example.json"


@pytest.fixture
def loaded_objects() -> dict[str, CustomObjectMetadata]:
    return load_salesforce_dx_objects(SF_OBJECTS_DIR)


@pytest.fixture
def default_config() -> SyncMappingConfig:
    return load_sync_mapping_config(DEFAULT_CONFIG_PATH)


class TestMetadataParsingAndCompatibility:
    def test_load_salesforce_dx_objects(self, loaded_objects: dict[str, CustomObjectMetadata]) -> None:
        assert "company__c" in loaded_objects
        assert "job__c" in loaded_objects

        comp = loaded_objects["company__c"]
        assert comp.label == "Company"
        assert comp.name_field_type == "Text"
        assert "canonical_company_id__c" in comp.fields
        assert comp.fields["canonical_company_id__c"].external_id is True
        assert comp.fields["canonical_company_id__c"].unique is True
        assert comp.fields["canonical_company_id__c"].case_sensitive is False
        assert comp.fields["canonical_company_id__c"].required is True

        job = loaded_objects["job__c"]
        assert job.label == "Job"
        assert "canonical_job_id__c" in job.fields
        assert job.fields["canonical_job_id__c"].external_id is True
        assert job.fields["canonical_job_id__c"].unique is True
        assert job.fields["canonical_job_id__c"].case_sensitive is False

        # Lookup field
        lookup = job.fields["company__c"]
        assert lookup.field_type == "Lookup"
        assert lookup.reference_to == "Company__c"
        assert lookup.delete_constraint == "Restrict"

        # Candidate progress creation default
        prog = job.fields["application_progress__c"]
        assert prog.field_type == "Picklist"
        assert prog.default_picklist_value == "New"
        assert "New" in prog.picklist_values
        assert "Interviewing" in prog.picklist_values

    def test_validate_default_config_compatibility(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        report = validate_metadata_compatibility(loaded_objects, default_config)
        assert report.compatible is True
        assert len(report.issues) == 0

    def test_validate_autonumber_config_compatibility(
        self, loaded_objects: dict[str, CustomObjectMetadata]
    ) -> None:
        cfg = load_sync_mapping_config(AUTONUMBER_CONFIG_PATH)
        report = validate_metadata_compatibility(loaded_objects, cfg)
        assert report.compatible is True
        assert len(report.issues) == 0

    def test_missing_company_object_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        bad_objs = {k: v for k, v in loaded_objects.items() if k != "company__c"}
        report = validate_metadata_compatibility(bad_objs, default_config)
        assert report.compatible is False
        assert any("Company object 'Company__c' is missing" in iss for iss in report.issues)

    def test_autonumber_name_collision_fails_when_mapped_for_write(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        # Simulate Job__c.Name being an AutoNumber
        objs = copy.deepcopy(loaded_objects)
        objs["job__c"].name_field_type = "AutoNumber"

        report = validate_metadata_compatibility(objs, default_config)
        assert report.compatible is False
        assert any("Job title field is mapped to standard 'Name', but 'Job__c.Name' is AutoNumber" in iss for iss in report.issues)

    def test_non_unique_external_id_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["job__c"].fields["canonical_job_id__c"]
        objs["job__c"].fields["canonical_job_id__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type=orig_f.field_type,
            unique=False,  # Not unique!
            external_id=True,
            case_sensitive=False,
        )

        report = validate_metadata_compatibility(objs, default_config)
        assert report.compatible is False
        assert any("must be Unique" in iss for iss in report.issues)

    def test_wrong_lookup_reference_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["job__c"].fields["company__c"]
        objs["job__c"].fields["company__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Lookup",
            reference_to="Account",  # Wrong reference!
            delete_constraint="Restrict",
        )

        report = validate_metadata_compatibility(objs, default_config)
        assert report.compatible is False
        assert any("references 'Account', but expected 'Company__c'" in iss for iss in report.issues)

    def test_missing_disposition_picklist_value_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["job__c"].fields["assessment_disposition__c"]
        objs["job__c"].fields["assessment_disposition__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Picklist",
            picklist_values=("Eligible", "Review"),  # Missing "Rejected"
        )

        report = validate_metadata_compatibility(objs, default_config)
        assert report.compatible is False
        assert any("missing mapped value 'Rejected'" in iss for iss in report.issues)

    def test_availability_with_default_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["job__c"].fields["availability__c"]
        objs["job__c"].fields["availability__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Picklist",
            picklist_values=orig_f.picklist_values,
            default_picklist_value="Active",  # Invalid default
        )

        report = validate_metadata_compatibility(objs, default_config)
        assert report.compatible is False
        assert any("Availability must not default automatically" in iss for iss in report.issues)

    def test_non_nullable_score_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["job__c"].fields["relevance_score__c"]
        objs["job__c"].fields["relevance_score__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Number",
            required=True,  # Non-nullable breaks null clearing!
        )

        report = validate_metadata_compatibility(objs, default_config)
        assert report.compatible is False
        assert any("must be nullable" in iss for iss in report.issues)

    def test_missing_candidate_progress_creation_default_fails(
        self, loaded_objects: dict[str, CustomObjectMetadata], default_config: SyncMappingConfig
    ) -> None:
        objs = copy.deepcopy(loaded_objects)
        orig_f = objs["job__c"].fields["application_progress__c"]
        objs["job__c"].fields["application_progress__c"] = CustomFieldMetadata(
            full_name=orig_f.full_name,
            label=orig_f.label,
            field_type="Picklist",
            picklist_values=orig_f.picklist_values,
            default_picklist_value=None,  # Missing New default
        )

        report = validate_metadata_compatibility(objs, default_config)
        assert report.compatible is False
        assert any("creation default must be 'New'" in iss for iss in report.issues)

