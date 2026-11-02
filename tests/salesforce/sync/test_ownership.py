"""Field ownership and collision tests for SYNC-01 (SYNC-01-S02)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_automation.salesforce.sync_errors import SyncOwnershipError
from job_automation.salesforce.sync_serialization import assert_no_candidate_fields
from job_automation.salesforce.sync_settings import SyncMappingConfig


class TestSyncOwnership:
    def test_ownership_collision_raises_sync_ownership_error(self) -> None:
        # Attempt to map title_field to Application_Progress__c (a candidate-owned field)
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected"):
            SyncMappingConfig(
                title_field="Application_Progress__c",
                candidate_fields=["Application_Progress__c", "Candidate_Notes__c"],
            )

    def test_ownership_collision_case_insensitive(self) -> None:
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected"):
            SyncMappingConfig(
                disposition_field="candidate_notes__c",
                candidate_fields=["Candidate_Notes__c"],
            )

    def test_assert_no_candidate_fields_clean_payload_passes(self) -> None:
        cfg = SyncMappingConfig()
        clean_payload = {
            "Name": "Software Engineer",
            "Availability__c": "Active",
            "Assessment_Disposition__c": "Eligible",
        }
        # Should not raise
        assert_no_candidate_fields(clean_payload, cfg)

    def test_assert_no_candidate_fields_polluted_payload_raises(self) -> None:
        cfg = SyncMappingConfig()
        polluted_payload = {
            "Name": "Software Engineer",
            "Application_Progress__c": "Applied",  # Candidate field!
        }
        with pytest.raises(SyncOwnershipError, match="Candidate-owned field.*illegally present"):
            assert_no_candidate_fields(polluted_payload, cfg)

    def test_invalid_salesforce_identifier_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid Salesforce identifier"):
            SyncMappingConfig(job_object="123InvalidJob")

    def test_candidate_field_aliasing_job_external_id_raises(self) -> None:
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected"):
            SyncMappingConfig(
                job_external_id_field="Canonical_Job_Id__c",
                candidate_fields=["Canonical_Job_Id__c"],
            )

    def test_candidate_field_aliasing_lookup_field_raises(self) -> None:
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected"):
            SyncMappingConfig(
                job_company_lookup_field="Company__c",
                candidate_fields=["Company__c"],
            )

    def test_intra_job_machine_roles_aliasing_raises(self) -> None:
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected: machine roles.*alias the same Job field"):
            SyncMappingConfig(
                title_field="SameField__c",
                disposition_field="SameField__c",
            )

    def test_intra_company_machine_roles_aliasing_raises(self) -> None:
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected: machine roles.*alias the same Company field"):
            SyncMappingConfig(
                company_external_id_field="SameCompField__c",
                company_name_field="SameCompField__c",
            )

    def test_company_and_job_object_sharing_name_raises(self) -> None:
        with pytest.raises(SyncOwnershipError, match="Ownership collision detected: company_object and job_object cannot share"):
            SyncMappingConfig(
                company_object="SameObject__c",
                job_object="SameObject__c",
            )


