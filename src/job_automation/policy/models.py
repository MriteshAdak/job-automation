"""Domain models for POLICY-01 search policy validation and metadata."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import CompensationProvenance, SalaryPeriod
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.policy import SearchPolicy

POLICY_SCHEMA_VERSION: str = "1.0"
POLICY_SEMANTICS_VERSION: str = "1.0"
NORMALIZATION_VERSION: str = "1.0"
CANONICALIZATION_VERSION: str = "1.0"


class SalaryOperand(ContractModel):
    """Structured operand for compensation criteria.

    Ambiguous bare numbers are rejected; monetary comparisons require
    explicit currency, period, and optional gross/net/provenance semantics.
    """

    amount: Decimal = Field(gt=0, description="Strictly positive compensation bound")
    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 three-letter currency code",
    )
    period: SalaryPeriod = Field(
        default=SalaryPeriod.YEARLY,
        description="Payment period (hourly, monthly, yearly)",
    )
    is_gross: bool | None = Field(
        default=None,
        description="Gross/net specification if stated; None if unspecified",
    )
    provenance: CompensationProvenance | None = Field(
        default=None,
        description="Required provenance if matching only employer-provided vs estimated",
    )


class EffectiveMissingAction(ContractModel):
    """Resolved missing-information action for a criterion."""

    action: Literal["pass", "fail", "unknown"] = Field(
        description="Action to take when posting target field is missing",
    )
    source: Literal["explicit_rule", "field_default", "global_default"] = Field(
        description="Where this disposition was derived from",
    )


class PolicyMetadata(ContractModel):
    """Provenance and version metadata for a validated policy."""

    authored_version: str = Field(
        min_length=1,
        description="Original user-authored policy_version string from input",
    )
    effective_version: str = Field(
        min_length=1,
        description="Computed deterministic version fingerprint bound to effective content",
    )
    schema_version: str = Field(default=POLICY_SCHEMA_VERSION)
    policy_semantics_version: str = Field(default=POLICY_SEMANTICS_VERSION)
    normalization_version: str = Field(default=NORMALIZATION_VERSION)
    canonicalization_version: str = Field(default=CANONICALIZATION_VERSION)


class EffectivePolicy(ContractModel):
    """Immutable, fully validated search policy ready for downstream execution."""

    policy: SearchPolicy = Field(
        description="Effective C02 SearchPolicy with policy_version bound to computed fingerprint",
    )
    metadata: PolicyMetadata = Field(
        description="Policy version, semantic, and normalization metadata",
    )
    effective_missing_actions: dict[str, EffectiveMissingAction] = Field(
        default_factory=dict,
        description="Criterion ID to materialized effective missing action",
    )
    canonical_bytes: bytes = Field(
        description="Deterministic canonical UTF-8 JSON bytes used to compute fingerprint",
    )


class PolicyValidationResult(ContractModel):
    """Result of loading and validating a search policy."""

    is_valid: bool = Field(description="True if validation passed with no errors")
    effective_policy: EffectivePolicy | None = Field(
        default=None,
        description="Validated effective policy; populated only when is_valid is True",
    )
    fingerprint: str | None = Field(
        default=None,
        description="Tagged SHA-256 fingerprint; populated only when is_valid is True",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="List of validation errors and warnings",
    )

    @property
    def errors(self) -> list[ValidationIssue]:
        """Return only error-level validation issues."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Return only warning-level validation issues."""
        return [i for i in self.issues if i.severity == "warning"]

