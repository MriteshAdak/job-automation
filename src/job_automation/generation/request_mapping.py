"""Salesforce Generation Request object and field mapping, ID canonicalization, and option digests."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.salesforce import validate_salesforce_identifier

# Namespace UUID for deterministic request IDs derived from Salesforce identity
UUID_NAMESPACE_SALESFORCE_REQUEST = uuid.UUID("d3b07384-d113-4b68-b3d4-b97c6d66e709")

_SF_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$")
_SF_LOOKUP = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"

# Maximum remote field string lengths matching Salesforce metadata definition bounds
MAX_CLIENT_KEY_LENGTH = 255
MAX_TEMPLATE_ID_LENGTH = 255
MAX_POSTING_REVISION_LENGTH = 255
MAX_PROFILE_VERSION_LENGTH = 255
MAX_POLICY_VERSION_LENGTH = 255
MAX_TEMPLATE_VERSION_LENGTH = 255
MAX_LOCAL_ARTIFACT_REF_LENGTH = 255
MAX_RESULT_ARTIFACT_REF_LENGTH = 255
MAX_ERROR_REASON_LENGTH = 255
MAX_ERROR_MESSAGE_LENGTH = 2000
MAX_ERROR_REF_LENGTH = 255
MAX_OPERATION_MARKER_LENGTH = 255
MAX_SCHEMA_VERSION_LENGTH = 16


def canonicalize_salesforce_id(sf_id: str) -> str:
    """Canonicalize a 15 or 18 character Salesforce ID into an 18-character case-safe representation.

    Strictly preserves case; never lowercases or uppercases the original 15 characters.
    Appends standard 3-character checksum suffix if 15 characters are supplied.
    """
    if not isinstance(sf_id, str):
        raise ValueError(f"Salesforce ID must be string, got {type(sf_id).__name__}")
    cleaned = sf_id.strip()
    if not _SF_ID_PATTERN.match(cleaned):
        raise ValueError(f"Invalid Salesforce ID format: '{sf_id}' (must be 15 or 18 alphanumeric characters)")

    if len(cleaned) == 18:
        return cleaned

    # Convert 15 characters to 18 characters using standard Salesforce bitmask checksum
    suffix = ""
    for i in range(3):
        block = cleaned[i * 5 : (i + 1) * 5]
        bitmask = 0
        for j, char in enumerate(block):
            if "A" <= char <= "Z":
                bitmask |= 1 << j
        suffix += _SF_LOOKUP[bitmask]

    return cleaned + suffix


def derive_local_request_id(org_id: str, canonical_sf_id: str) -> uuid.UUID:
    """Derive a stable, deterministic UUIDv5 for UI-created requests without a local UUID."""
    canonical_org = canonicalize_salesforce_id(org_id)
    canonical_req = canonicalize_salesforce_id(canonical_sf_id)
    name = f"{canonical_org}:{canonical_req}"
    return uuid.uuid5(UUID_NAMESPACE_SALESFORCE_REQUEST, name)


def compute_options_digest(options: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 digest over normalized request generation options."""
    normalized: dict[str, Any] = {}
    for k, v in sorted(options.items()):
        if isinstance(v, uuid.UUID):
            normalized[k] = str(v)
        elif hasattr(v, "value"):
            normalized[k] = v.value
        else:
            normalized[k] = v
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RequestFieldMapping(ContractModel):
    """Configuration mapping between Salesforce sObject and internal generation request fields."""

    schema_version: str = Field(default="1.0")
    mapping_version: str = Field(default="1.0")
    expected_org_id: str = Field(default="00D000000000001EAA")

    # Target sObject name
    request_object: str = Field(default="Generation_Request__c")

    # Creation/Input fields on Generation_Request__c
    job_lookup_field: str = Field(default="Job__c")
    document_type_field: str = Field(default="Document_Type__c")
    target_language_field: str = Field(default="Language__c")
    template_id_field: str = Field(default="Template_Id__c")
    context_strategy_field: str = Field(default="Context_Strategy__c")
    allow_unavailable_field: str = Field(default="Allow_Unavailable_Job__c")
    predecessor_field: str = Field(default="Predecessor_Request__c")
    client_key_field: str = Field(default="Client_Request_Key__c")
    schema_version_field: str = Field(default="Contract_Schema_Version__c")

    # Worker/Execution fields on Generation_Request__c
    status_field: str = Field(default="Status__c")
    worker_claimed_at_field: str = Field(default="Worker_Claimed_At__c")
    completed_at_field: str = Field(default="Completed_At__c")
    frozen_posting_revision_field: str = Field(default="Frozen_Posting_Revision__c")
    frozen_profile_version_field: str = Field(default="Frozen_Profile_Version__c")
    frozen_policy_version_field: str = Field(default="Frozen_Policy_Version__c")
    frozen_template_version_field: str = Field(default="Frozen_Template_Version__c")
    local_artifact_ref_field: str = Field(default="Local_Artifact_Ref__c")
    result_artifact_field: str = Field(default="Result_Artifact_Ref__c")
    error_category_field: str = Field(default="Error_Category__c")
    error_reason_field: str = Field(default="Error_Reason__c")
    error_message_field: str = Field(default="Error_Message__c")
    error_ref_field: str = Field(default="Error_Ref__c")
    operation_marker_field: str = Field(default="Operation_Marker__c")

    def validate_identifiers(self) -> None:
        """Validate that all mapped field and object names are valid Salesforce identifiers."""
        validate_salesforce_identifier(self.request_object, "request_object")
        validate_salesforce_identifier(self.job_lookup_field, "job_lookup_field")
        validate_salesforce_identifier(self.document_type_field, "document_type_field")
        validate_salesforce_identifier(self.target_language_field, "target_language_field")
        validate_salesforce_identifier(self.template_id_field, "template_id_field")
        validate_salesforce_identifier(self.context_strategy_field, "context_strategy_field")
        validate_salesforce_identifier(self.allow_unavailable_field, "allow_unavailable_field")
        validate_salesforce_identifier(self.predecessor_field, "predecessor_field")
        validate_salesforce_identifier(self.client_key_field, "client_key_field")
        validate_salesforce_identifier(self.schema_version_field, "schema_version_field")
        validate_salesforce_identifier(self.status_field, "status_field")
        validate_salesforce_identifier(self.worker_claimed_at_field, "worker_claimed_at_field")
        validate_salesforce_identifier(self.completed_at_field, "completed_at_field")
        validate_salesforce_identifier(self.frozen_posting_revision_field, "frozen_posting_revision_field")
        validate_salesforce_identifier(self.frozen_profile_version_field, "frozen_profile_version_field")
        validate_salesforce_identifier(self.frozen_policy_version_field, "frozen_policy_version_field")
        validate_salesforce_identifier(self.frozen_template_version_field, "frozen_template_version_field")
        validate_salesforce_identifier(self.local_artifact_ref_field, "local_artifact_ref_field")
        validate_salesforce_identifier(self.result_artifact_field, "result_artifact_field")
        validate_salesforce_identifier(self.error_category_field, "error_category_field")
        validate_salesforce_identifier(self.error_reason_field, "error_reason_field")
        validate_salesforce_identifier(self.error_message_field, "error_message_field")
        validate_salesforce_identifier(self.error_ref_field, "error_ref_field")
        validate_salesforce_identifier(self.operation_marker_field, "operation_marker_field")

    @model_validator(mode="after")
    def _validate_ownership_and_no_aliasing(self) -> RequestFieldMapping:
        # Check that no two distinct roles map to the same physical field name
        field_roles = {
            "job_lookup_field": self.job_lookup_field.strip().lower(),
            "document_type_field": self.document_type_field.strip().lower(),
            "target_language_field": self.target_language_field.strip().lower(),
            "template_id_field": self.template_id_field.strip().lower(),
            "context_strategy_field": self.context_strategy_field.strip().lower(),
            "allow_unavailable_field": self.allow_unavailable_field.strip().lower(),
            "predecessor_field": self.predecessor_field.strip().lower(),
            "client_key_field": self.client_key_field.strip().lower(),
            "schema_version_field": self.schema_version_field.strip().lower(),
            "status_field": self.status_field.strip().lower(),
            "worker_claimed_at_field": self.worker_claimed_at_field.strip().lower(),
            "completed_at_field": self.completed_at_field.strip().lower(),
            "frozen_posting_revision_field": self.frozen_posting_revision_field.strip().lower(),
            "frozen_profile_version_field": self.frozen_profile_version_field.strip().lower(),
            "frozen_policy_version_field": self.frozen_policy_version_field.strip().lower(),
            "frozen_template_version_field": self.frozen_template_version_field.strip().lower(),
            "local_artifact_ref_field": self.local_artifact_ref_field.strip().lower(),
            "result_artifact_field": self.result_artifact_field.strip().lower(),
            "error_category_field": self.error_category_field.strip().lower(),
            "error_reason_field": self.error_reason_field.strip().lower(),
            "error_message_field": self.error_message_field.strip().lower(),
            "error_ref_field": self.error_ref_field.strip().lower(),
            "operation_marker_field": self.operation_marker_field.strip().lower(),
        }

        seen: dict[str, str] = {}
        for role, fld in field_roles.items():
            if fld in seen:
                raise ValueError(
                    f"Ownership aliasing collision: roles '{seen[fld]}' and '{role}' alias the same field '{fld}'"
                )
            seen[fld] = role

        return self


def validate_request_field_lengths(
    payload: dict[str, Any],
    mapping: RequestFieldMapping | None = None,
) -> list[str]:
    """Validate string field lengths against metadata limits before dispatch.

    Returns a list of actionable error descriptions for any overlength fields.
    """
    m = mapping or RequestFieldMapping()
    issues: list[str] = []

    limits = {
        m.client_key_field: (MAX_CLIENT_KEY_LENGTH, "Client Request Key"),
        m.template_id_field: (MAX_TEMPLATE_ID_LENGTH, "Template ID"),
        m.frozen_posting_revision_field: (MAX_POSTING_REVISION_LENGTH, "Frozen Posting Revision"),
        m.frozen_profile_version_field: (MAX_PROFILE_VERSION_LENGTH, "Frozen Profile Version"),
        m.frozen_policy_version_field: (MAX_POLICY_VERSION_LENGTH, "Frozen Policy Version"),
        m.frozen_template_version_field: (MAX_TEMPLATE_VERSION_LENGTH, "Frozen Template Version"),
        m.local_artifact_ref_field: (MAX_LOCAL_ARTIFACT_REF_LENGTH, "Local Artifact Reference"),
        m.result_artifact_field: (MAX_RESULT_ARTIFACT_REF_LENGTH, "Result Artifact Reference"),
        m.error_reason_field: (MAX_ERROR_REASON_LENGTH, "Error Reason"),
        m.error_message_field: (MAX_ERROR_MESSAGE_LENGTH, "Error Message"),
        m.error_ref_field: (MAX_ERROR_REF_LENGTH, "Error Reference"),
        m.operation_marker_field: (MAX_OPERATION_MARKER_LENGTH, "Operation Marker"),
        m.schema_version_field: (MAX_SCHEMA_VERSION_LENGTH, "Contract Schema Version"),
    }

    for field_name, (max_len, desc) in limits.items():
        val = payload.get(field_name)
        if val is not None and isinstance(val, str) and len(val) > max_len:
            issues.append(
                f"{desc} ('{field_name}') exceeds maximum remote length {max_len} (length: {len(val)})"
            )

    return issues


_SECRET_PATTERNS = [
    re.compile(r"(?:password|secret|bearer\s+[a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
    re.compile(r"00D[A-Za-z0-9]{12,15}![A-Za-z0-9._]+"),  # Salesforce session ID pattern
    re.compile(r"[A-Za-z]:\\[^ \n\r\t]+"),  # Windows absolute file path
]


def sanitize_error_message(message: str) -> str:
    """Sanitize error messages by redacting credentials/paths and capping to metadata length."""
    if not message:
        return ""
    sanitized = message
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    if len(sanitized) > MAX_ERROR_MESSAGE_LENGTH:
        sanitized = sanitized[: MAX_ERROR_MESSAGE_LENGTH - 16] + "... [TRUNCATED]"
    return sanitized

