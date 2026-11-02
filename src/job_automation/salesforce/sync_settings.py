"""SYNC-01 configuration and mapping models (SYNC-01-S02).

Defines:
- SyncMappingConfig: non-secret mapping between canonical entities and Salesforce sObjects
- Picklist conversions, field ownership validation, and deterministic mapping hash
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.salesforce import validate_salesforce_identifier
from job_automation.salesforce.sync_errors import SyncOwnershipError, SyncValidationError

# TODO(SF-01/SF-00): Verify the selected org (currently alias dev-main).
# Resolve its org ID, endpoint and supported API version; inspect object/field
# names, External IDs, lookup targets, picklists, required fields and defaults.
# Supply verified values through SalesforceSettings and SyncMappingConfig.
# Revalidate mappings and migration needs whenever the target org changes.


DEFAULT_DISPOSITION_MAPPING: dict[str, str] = {
    "eligible": "Eligible",
    "review": "Review",
    "rejected": "Rejected",
}

DEFAULT_AVAILABILITY_MAPPING: dict[str, str] = {
    "active": "Active",
    "not_seen": "Not Seen",
    "unavailable": "Unavailable",
    "unknown": "Unknown",
}

DEFAULT_CANDIDATE_FIELDS: list[str] = [
    "Application_Progress__c",
    "Candidate_Notes__c",
    "Candidate_Decision__c",
    "Follow_Up_Date__c",
    "Interview_Date__c",
]


class SyncMappingConfig(ContractModel):
    """Non-secret field mapping and ownership configuration."""

    schema_version: str = Field(default="1.0", description="Contract schema version")
    mapping_version: str = Field(default="1.0", description="Version token of this mapping")
    expected_org_id: str = Field(
        default="00D000000000001", description="Expected 15 or 18-char Salesforce Org ID"
    )

    # Company object mapping
    company_object: str = Field(
        default="Company__c", description="Salesforce sObject API name for companies"
    )
    company_external_id_field: str = Field(
        default="Canonical_Company_Id__c",
        description="External ID field on Company object",
    )
    company_name_field: str = Field(
        default="Name", description="Field on Company storing canonical company name"
    )

    # Job object mapping
    job_object: str = Field(
        default="Job__c", description="Salesforce sObject API name for jobs"
    )
    job_external_id_field: str = Field(
        default="Canonical_Job_Id__c",
        description="External ID field on Job object",
    )
    job_company_lookup_field: str = Field(
        default="Company__c",
        description="Relationship lookup field on Job pointing to Company",
    )

    # Machine-owned fields on Job
    title_field: str = Field(
        default="Name", description="Job title field on Job object"
    )
    availability_field: str = Field(
        default="Availability__c", description="Job posting availability picklist field"
    )
    disposition_field: str = Field(
        default="Assessment_Disposition__c",
        description="Machine assessment disposition picklist field",
    )
    reason_field: str = Field(
        default="Assessment_Reasons__c",
        description="Machine assessment summary reasons field",
    )
    score_field: str = Field(
        default="Relevance_Score__c",
        description="Machine assessment relevance score field",
    )
    score_scale_field: str = Field(
        default="Score_Scale__c",
        description="Score scale declaration field",
    )
    last_evaluated_field: str = Field(
        default="Last_Evaluated_At__c",
        description="Timestamp when assessment was evaluated",
    )
    source_urls_field: str = Field(
        default="Source_URLs__c",
        description="Field storing observed posting source URLs",
    )
    sync_marker_field: str = Field(
        default="Sync_Operation_Marker__c",
        description="Reconciliation marker field written into Job record",
    )
    sync_version_field: str = Field(
        default="Machine_Sync_Version__c",
        description="Numeric sequence version field written into Job record",
    )

    # Picklist value maps
    disposition_mapping: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_DISPOSITION_MAPPING),
        description="Mapping from local disposition to Salesforce picklist value",
    )
    availability_mapping: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_AVAILABILITY_MAPPING),
        description="Mapping from local availability to Salesforce picklist value",
    )

    # Candidate-owned fields (allowlist for reading and local backup, strictly excluded from writes)
    candidate_fields: list[str] = Field(
        default_factory=lambda: list(DEFAULT_CANDIDATE_FIELDS),
        description="Candidate-owned fields on Job__c; read for snapshots, forbidden from outbound writes",
    )

    @field_validator(
        "company_object",
        "company_external_id_field",
        "company_name_field",
        "job_object",
        "job_external_id_field",
        "job_company_lookup_field",
        "title_field",
        "availability_field",
        "disposition_field",
        "reason_field",
        "score_field",
        "score_scale_field",
        "last_evaluated_field",
        "source_urls_field",
        "sync_marker_field",
        "sync_version_field",
    )
    @classmethod
    def _validate_sf_identifier(cls, v: str) -> str:
        return validate_salesforce_identifier(v)

    @field_validator("candidate_fields")
    @classmethod
    def _validate_candidate_field_names(cls, fields: list[str]) -> list[str]:
        for f in fields:
            validate_salesforce_identifier(f, field_desc="candidate field")
        return fields

    @model_validator(mode="after")
    def _validate_ownership_separation(self) -> SyncMappingConfig:
        if self.company_object.strip().lower() == self.job_object.strip().lower():
            raise SyncOwnershipError(
                f"Ownership collision detected: company_object and job_object cannot share the same API name '{self.company_object}'"
            )

        # Intra-entity machine collisions on Job
        job_machine_map = {
            "job_external_id_field": self.job_external_id_field.strip().lower(),
            "title_field": self.title_field.strip().lower(),
            "job_company_lookup_field": self.job_company_lookup_field.strip().lower(),
            "availability_field": self.availability_field.strip().lower(),
            "disposition_field": self.disposition_field.strip().lower(),
            "reason_field": self.reason_field.strip().lower(),
            "score_field": self.score_field.strip().lower(),
            "score_scale_field": self.score_scale_field.strip().lower(),
            "last_evaluated_field": self.last_evaluated_field.strip().lower(),
            "source_urls_field": self.source_urls_field.strip().lower(),
            "sync_marker_field": self.sync_marker_field.strip().lower(),
            "sync_version_field": self.sync_version_field.strip().lower(),
        }
        seen_job_fields: dict[str, str] = {}
        for role, fld in job_machine_map.items():
            if fld in seen_job_fields:
                raise SyncOwnershipError(
                    f"Ownership collision detected: machine roles '{seen_job_fields[fld]}' and '{role}' alias the same Job field '{fld}'"
                )
            seen_job_fields[fld] = role

        # Intra-entity machine collisions on Company
        comp_machine_map = {
            "company_external_id_field": self.company_external_id_field.strip().lower(),
            "company_name_field": self.company_name_field.strip().lower(),
            "sync_marker_field": self.sync_marker_field.strip().lower(),
            "sync_version_field": self.sync_version_field.strip().lower(),
        }
        seen_comp_fields: dict[str, str] = {}
        for role, fld in comp_machine_map.items():
            if fld in seen_comp_fields:
                raise SyncOwnershipError(
                    f"Ownership collision detected: machine roles '{seen_comp_fields[fld]}' and '{role}' alias the same Company field '{fld}'"
                )
            seen_comp_fields[fld] = role

        # Collision between candidate fields and machine job fields
        machine_job_fields = set(job_machine_map.values())
        candidate_field_set = {f.strip().lower() for f in self.candidate_fields}

        collision = machine_job_fields.intersection(candidate_field_set)
        if collision:
            raise SyncOwnershipError(
                f"Ownership collision detected between machine fields and candidate fields: {collision}"
            )
        return self

    def compute_hash(self) -> str:
        """Calculate deterministic SHA-256 hash of this mapping configuration."""
        dumped = self.model_dump(mode="json")
        canonical_bytes = json.dumps(dumped, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()


def load_sync_mapping_config(path: Path | str) -> SyncMappingConfig:
    """Load and validate SyncMappingConfig from a JSON file."""
    p = Path(path).resolve()
    if not p.is_file():
        raise SyncValidationError(f"Sync mapping configuration file not found at '{p}'")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return SyncMappingConfig.model_validate(data)

