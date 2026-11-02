"""SFCLIENT-01 Salesforce gateway contract models and typed operations.

Defines:
- Operation kinds, remote outcomes, and recovery actions
- GatewayResult and GatewayFailure envelopes with strict exclusivity
- Typed request and result records for reads and mutations
- Safe attempt summaries and validation guards
"""

from __future__ import annotations

import math
import re
import uuid
from enum import StrEnum
from typing import Any, Generic, Self, TypeVar

from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime

T = TypeVar("T")

# Salesforce API identifier pattern (standard or custom object/field)
# Examples: Job__c, Company__c, Id, External_Id__c, Name, Account
SF_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


def validate_salesforce_identifier(name: str, field_desc: str = "identifier") -> str:
    """Validate that a string conforms to Salesforce API identifier rules."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Salesforce {field_desc} must be a non-empty string.")
    cleaned = name.strip()
    if not SF_IDENTIFIER_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid Salesforce {field_desc} '{name}'. Must start with a letter, "
            "contain only alphanumeric characters and underscores, and be at most 80 characters."
        )
    return cleaned


def validate_bounded_json_value(val: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Recursively validate that JSON-like values are bounded, finite, and well-formed."""
    if depth > max_depth:
        raise ValueError(f"Payload exceeds maximum allowable nesting depth of {max_depth}.")

    if val is None or isinstance(val, (str, bool, int)):
        return val
    elif isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise ValueError("Floats must be finite (NaN and Infinity are forbidden).")
        return val
    elif isinstance(val, (list, tuple)):
        if len(val) > 1000:
            raise ValueError(f"Sequence length {len(val)} exceeds limit of 1000 elements.")
        return [validate_bounded_json_value(item, depth + 1, max_depth) for item in val]
    elif isinstance(val, dict):
        if len(val) > 200:
            raise ValueError(f"Dictionary size {len(val)} exceeds limit of 200 keys.")
        validated: dict[str, Any] = {}
        for k, v in val.items():
            if not isinstance(k, str):
                raise ValueError(f"Dictionary key must be string, got {type(k).__name__}.")
            validated[k] = validate_bounded_json_value(v, depth + 1, max_depth)
        return validated
    elif isinstance(val, uuid.UUID):
        return str(val)
    else:
        raise ValueError(f"Unsupported payload value type '{type(val).__name__}'.")


# ===================================================================
# Enums and Summary Records
# ===================================================================


class OperationKind(StrEnum):
    """Supported typed Salesforce operations."""

    CHECK_CONNECTION = "check_connection"
    GET_LIMITS = "get_limits"
    DESCRIBE_OBJECT = "describe_object"
    GET_RECORD = "get_record"
    QUERY_PAGE = "query_page"
    UPSERT_BY_EXTERNAL_ID = "upsert_by_external_id"
    UPDATE_RECORD = "update_record"


class RemoteOutcome(StrEnum):
    """Observed state of remote record mutation."""

    NOT_SENT = "not_sent"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    ACKNOWLEDGED = "acknowledged"


class RecoveryAction(StrEnum):
    """Actionable guidance for failure resolution."""

    NONE = "none"
    RETRY_LATER = "retry_later"
    REAUTHORIZE = "reauthorize"
    RECONCILE = "reconcile"
    FIX_CONFIGURATION = "fix_configuration"


class AttemptSummary(ContractModel):
    """Summary of a single HTTP attempt during a gateway operation."""

    attempt_number: int = Field(ge=1, description="1-based attempt sequence index")
    purpose: str = Field(description="Purpose of attempt (e.g. token_acquisition, resource_request)")
    http_status: int | None = Field(default=None, description="HTTP response status code if response received")
    duration_ms: float = Field(ge=0.0, description="Observed roundtrip duration in milliseconds")
    safe_code: str | None = Field(default=None, description="Allowlisted safe status/error code")
    uncertain_transmission: bool = Field(
        default=False,
        description="Whether request transmission to Salesforce was uncertain (e.g. timeout after send)",
    )


class GatewayFailure(ContractModel):
    """Structured failure representation for gateway operations."""

    error: ClassifiedError = Field(description="Classified system error")
    safe_provider_code: str | None = Field(default=None, description="Allowlisted Salesforce error code")
    http_status: int | None = Field(default=None, description="HTTP status code if available")
    operation_kind: OperationKind = Field(description="Gateway operation kind that failed")
    remote_outcome: RemoteOutcome = Field(description="Observed mutation outcome on Salesforce")
    recovery_action: RecoveryAction = Field(description="Actionable recovery instruction")
    retry_not_before: UtcDatetime | None = Field(
        default=None, description="Server-directed or backoff wait ceiling"
    )
    exhausted_budget: bool = Field(default=False, description="Whether call budget or retry count was exhausted")
    attempts: list[AttemptSummary] = Field(
        default_factory=list, description="Audit trace of HTTP attempts made"
    )


class GatewayResult(ContractModel, Generic[T]):
    """Result envelope for typed Salesforce gateway operations.

    Enforces strict exclusivity: exactly one of value OR failure is set.
    """

    value: T | None = Field(default=None, description="Typed operation result on success")
    failure: GatewayFailure | None = Field(default=None, description="Gateway failure if unsuccessful")
    attempts: list[AttemptSummary] = Field(
        default_factory=list, description="All HTTP attempts executed for this call"
    )

    @model_validator(mode="after")
    def _validate_exclusivity(self) -> Self:
        has_val = self.value is not None
        has_fail = self.failure is not None
        if has_val == has_fail:
            raise ValueError(
                "GatewayResult must contain exactly one of 'value' or 'failure', never both or neither."
            )
        return self

    @classmethod
    def success(cls, value: T, attempts: list[AttemptSummary] | None = None) -> GatewayResult[T]:
        """Create a successful GatewayResult."""
        return cls(value=value, failure=None, attempts=attempts or [])

    @classmethod
    def fail(cls, failure: GatewayFailure, attempts: list[AttemptSummary] | None = None) -> GatewayResult[T]:
        """Create a failed GatewayResult."""
        att = attempts if attempts is not None else failure.attempts
        return cls(value=None, failure=failure, attempts=att)

    @property
    def is_success(self) -> bool:
        return self.value is not None

    @property
    def is_failure(self) -> bool:
        return self.failure is not None


# ===================================================================
# Operation Requests and Results
# ===================================================================


class ConnectionCheckRequest(ContractModel):
    """Request for verifying connectivity and identity with Salesforce."""

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Caller-generated operation UUID")
    expected_org_id: str | None = Field(default=None, description="Expected 15 or 18 char Salesforce Org ID")
    expected_user_id: str | None = Field(default=None, description="Expected Salesforce User ID")
    perform_network_check: bool = Field(
        default=True, description="Explicit opt-in to network validation check"
    )


class ConnectionCheckResult(ContractModel):
    """Result of connection verification."""

    connected: bool = Field(description="Whether connection and identity are verified")
    org_id: str | None = Field(default=None, description="Confirmed Salesforce Org ID")
    user_id: str | None = Field(default=None, description="Confirmed Salesforce User ID")
    instance_url: str = Field(description="Active Salesforce instance origin URL")
    api_version: str = Field(description="Configured and confirmed Salesforce REST API version")
    identity_endpoint_verified: bool = Field(
        default=True, description="Whether identity was verified via approved endpoint"
    )


class LimitsRequest(ContractModel):
    """Request to fetch organization API limits."""

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Caller-generated operation UUID")


class LimitsResult(ContractModel):
    """Observed organization API limits."""

    daily_api_requests_max: int | None = Field(default=None, ge=0)
    daily_api_requests_remaining: int | None = Field(default=None, ge=0)
    raw_limits: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="Typed named limit categories"
    )


class DescribeObjectRequest(ContractModel):
    """Request to describe metadata for a specific Salesforce sObject."""

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Caller-generated operation UUID")
    object_name: str = Field(description="Target sObject API name (e.g. Job__c)")

    @field_validator("object_name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return validate_salesforce_identifier(v, "object_name")


class DescribeFieldResult(ContractModel):
    """Metadata capabilities for a single sObject field."""

    name: str = Field(description="Field API name")
    label: str = Field(description="Display label")
    type: str = Field(description="Salesforce field data type")
    createable: bool = Field(description="Whether field is createable")
    updateable: bool = Field(description="Whether field is updateable")
    id_lookup: bool = Field(default=False, description="Whether field can be used for idLookup")
    external_id: bool = Field(default=False, description="Whether field is an External ID")


class DescribeObjectResult(ContractModel):
    """Metadata description of a Salesforce sObject."""

    object_name: str = Field(description="sObject API name")
    label: str = Field(description="Display label")
    custom: bool = Field(description="Whether this is a custom sObject")
    key_prefix: str | None = Field(default=None, description="3-character key prefix")
    fields: dict[str, DescribeFieldResult] = Field(
        default_factory=dict, description="Field definitions keyed by API name"
    )
    external_id_fields: list[str] = Field(
        default_factory=list, description="List of fields designated as External IDs"
    )


class GetRecordRequest(ContractModel):
    """Request to retrieve selected fields of a specific record by ID or External ID."""

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Caller-generated operation UUID")
    object_name: str = Field(description="Target sObject API name")
    record_id: str | None = Field(default=None, description="Standard Salesforce 15 or 18 char Record ID")
    external_id_field: str | None = Field(default=None, description="External ID field API name")
    external_id_value: str | None = Field(default=None, description="External ID lookup value")
    fields: list[str] = Field(min_length=1, description="Explicit list of field API names to retrieve")

    @field_validator("object_name")
    @classmethod
    def _validate_obj(cls, v: str) -> str:
        return validate_salesforce_identifier(v, "object_name")

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for f in v:
            cleaned.append(validate_salesforce_identifier(f, "field name"))
        return cleaned

    @model_validator(mode="after")
    def _validate_selector(self) -> Self:
        has_id = bool(self.record_id and self.record_id.strip())
        has_ext = bool(
            self.external_id_field and self.external_id_field.strip() and self.external_id_value is not None
        )
        if has_id == has_ext:
            raise ValueError(
                "GetRecordRequest must provide exactly one selector: either record_id OR "
                "(external_id_field and external_id_value), never both or neither."
            )
        if self.external_id_field:
            validate_salesforce_identifier(self.external_id_field, "external_id_field")
        return self


class GetRecordResult(ContractModel):
    """Retrieved record envelope."""

    object_name: str = Field(description="sObject API name")
    record_id: str = Field(description="Salesforce Record ID")
    fields: dict[str, Any] = Field(description="Retrieved field values keyed by API name")


class QueryPageRequest(ContractModel):
    """Request to execute a SOQL query page or fetch next page via continuation."""

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Caller-generated operation UUID")
    soql: str | None = Field(default=None, description="Caller-built SOQL string for first page")
    continuation_token: str | None = Field(
        default=None, description="Opaque nextRecordsUrl or cursor token"
    )

    @model_validator(mode="after")
    def _validate_query_input(self) -> Self:
        has_soql = bool(self.soql and self.soql.strip())
        has_token = bool(self.continuation_token and self.continuation_token.strip())
        if has_soql == has_token:
            raise ValueError(
                "QueryPageRequest must supply either 'soql' for initial page OR "
                "'continuation_token' for subsequent page, never both or neither."
            )
        return self


class QueryPageResult(ContractModel):
    """Single page result of a SOQL query."""

    total_size: int = Field(ge=0, description="Total matching records count")
    done: bool = Field(description="Whether this query has no further pages")
    records: list[dict[str, Any]] = Field(default_factory=list, description="Records in this page")
    next_records_url: str | None = Field(
        default=None, description="Relative continuation path for next page if not done"
    )


class UpsertRequest(ContractModel):
    """Request to upsert an sObject record using an External ID."""

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Caller-generated operation UUID")
    object_name: str = Field(description="Target sObject API name")
    external_id_field: str = Field(description="External ID field API name")
    external_id_value: str = Field(min_length=1, description="External ID unique value")
    fields: dict[str, Any] = Field(min_length=1, description="Caller-mapped field values to update/create")
    replay_safe: bool = Field(
        default=False,
        description="Whether caller guarantees idempotent replay is safe for this specific mutation",
    )

    @field_validator("object_name")
    @classmethod
    def _validate_obj(cls, v: str) -> str:
        return validate_salesforce_identifier(v, "object_name")

    @field_validator("external_id_field")
    @classmethod
    def _validate_ext_field(cls, v: str) -> str:
        return validate_salesforce_identifier(v, "external_id_field")

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, v: dict[str, Any]) -> dict[str, Any]:
        for k in v.keys():
            validate_salesforce_identifier(k, "payload field key")
        return validate_bounded_json_value(v)


class UpsertResult(ContractModel):
    """Acknowledgment of an External ID upsert operation."""

    object_name: str = Field(description="Target sObject API name")
    external_id_field: str = Field(description="External ID field name")
    external_id_value: str = Field(description="External ID value")
    record_id: str = Field(description="Salesforce Record ID of created or updated record")
    created: bool = Field(description="True if record was newly created (201), False if updated (200/204)")
    acknowledged_at: UtcDatetime = Field(description="Timestamp when Salesforce acknowledged mutation")


class UpdateRequest(ContractModel):
    """Request to update an existing record by known Salesforce Record ID."""

    call_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Caller-generated operation UUID")
    object_name: str = Field(description="Target sObject API name")
    record_id: str = Field(min_length=15, max_length=18, description="Target Salesforce Record ID")
    fields: dict[str, Any] = Field(min_length=1, description="Fields to patch on record")

    @field_validator("object_name")
    @classmethod
    def _validate_obj(cls, v: str) -> str:
        return validate_salesforce_identifier(v, "object_name")

    @field_validator("record_id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not re.match(r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$", v):
            raise ValueError(f"Invalid Salesforce record ID format: '{v}'")
        return v

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, v: dict[str, Any]) -> dict[str, Any]:
        for k in v.keys():
            validate_salesforce_identifier(k, "payload field key")
        return validate_bounded_json_value(v)


class UpdateResult(ContractModel):
    """Acknowledgment of a record update."""

    object_name: str = Field(description="Target sObject API name")
    record_id: str = Field(description="Salesforce Record ID updated")
    acknowledged_at: UtcDatetime = Field(description="Timestamp when Salesforce acknowledged update")

