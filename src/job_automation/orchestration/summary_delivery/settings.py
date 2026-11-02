"""Summary delivery configuration models and loader (AUTO-03-S05).

Provides:
- SummaryDeliverySettings: Versioned, bounded configuration for per-run summary delivery.
- Helper to safely load and resolve settings from JSON configuration files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.salesforce import validate_salesforce_identifier


class SummaryDeliverySettings(ContractModel):
    """Configuration governing per-run summary delivery to Salesforce."""

    schema_version: str = Field(
        default="1.0",
        description="Settings schema version",
    )
    enabled: bool = Field(
        default=False,
        description="Master opt-in flag; disabled by default to prevent unintended writes",
    )
    salesforce_org_id: str | None = Field(
        default=None,
        description="Expected 15 or 18 character Salesforce Organization ID",
    )
    test_recipient: str | None = Field(
        default=None,
        description="Explicit test recipient identifier/email required for live notification checks",
    )
    max_dispatch_attempts: int = Field(
        ge=1,
        le=20,
        default=5,
        description="Maximum lifetime dispatch attempts before transitioning to EXHAUSTED",
    )
    max_reconcile_attempts: int = Field(
        ge=1,
        le=20,
        default=5,
        description="Maximum lifetime reconciliation attempts before transitioning to EXHAUSTED",
    )
    max_recovery_age_hours: int = Field(
        ge=1,
        le=168,
        default=48,
        description="Maximum age in hours during which unfinalized deliveries will be retried",
    )
    initial_backoff_seconds: float = Field(
        ge=0.1,
        le=60.0,
        default=2.0,
        description="Initial exponential backoff delay in seconds",
    )
    max_backoff_seconds: float = Field(
        ge=1.0,
        le=3600.0,
        default=300.0,
        description="Ceiling for exponential backoff delay in seconds",
    )
    backoff_multiplier: float = Field(
        ge=1.0,
        le=4.0,
        default=2.0,
        description="Multiplier for exponential backoff calculations",
    )
    jitter_ratio: float = Field(
        ge=0.0,
        le=0.5,
        default=0.1,
        description="Randomized jitter fraction applied to backoff delays",
    )
    per_call_timeout_seconds: float = Field(
        ge=1.0,
        le=120.0,
        default=15.0,
        description="Per-operation HTTP timeout in seconds",
    )
    max_records_per_drain: int = Field(
        ge=1,
        le=200,
        default=50,
        description="Maximum number of due deliveries processed in a single drain invocation",
    )
    activation_epoch_utc: UtcDatetime | None = Field(
        default=None,
        description="Earliest run completion timestamp eligible for delivery (prevents backfill flooding)",
    )
    target_object_name: str = Field(
        default="Run_Summary__c",
        description="Target Salesforce sObject API name",
    )
    target_external_id_field: str = Field(
        default="Run_Id__c",
        description="External ID field on the target sObject",
    )
    mapping_version: str = Field(
        default="1.0",
        description="Field mapping contract version",
    )

    @field_validator("target_object_name")
    @classmethod
    def _validate_obj(cls, v: str) -> str:
        return validate_salesforce_identifier(v, "target_object_name")

    @field_validator("target_external_id_field")
    @classmethod
    def _validate_ext_field(cls, v: str) -> str:
        return validate_salesforce_identifier(v, "target_external_id_field")


def load_summary_delivery_settings(
    settings_path: str | Path | None,
) -> SummaryDeliverySettings:
    """Load SummaryDeliverySettings from a JSON file, or return safe disabled defaults."""
    if settings_path is None:
        return SummaryDeliverySettings()

    path = Path(settings_path)
    if not path.is_file():
        raise FileNotFoundError(f"Summary delivery settings file not found: '{settings_path}'")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return SummaryDeliverySettings.model_validate(data)

