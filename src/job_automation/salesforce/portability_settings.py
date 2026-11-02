"""Configuration settings for Salesforce capacity policy, metadata portability, and data export (SF-04).

Enforces:
- Configurable operational headroom reserves for data storage, file storage, and API requests.
- Warning multipliers separate from org-level quotas.
- Default export staging and destination roots outside source control.
- Non-secret policy configuration.
"""

from __future__ import annotations

import json
from pathlib import Path
from pydantic import Field

from job_automation.contracts.base import ContractModel


class CapacityPolicySettings(ContractModel):
    """Headroom thresholds and reserve parameters for capacity evaluation."""

    data_storage_reserve_mb: float = Field(
        default=5.0, ge=0.0, description="Minimum absolute data storage headroom in MB"
    )
    data_storage_reserve_percent: float = Field(
        default=10.0, ge=0.0, le=100.0, description="Minimum percentage data storage reserve"
    )
    file_storage_reserve_mb: float = Field(
        default=10.0, ge=0.0, description="Minimum absolute file storage headroom in MB"
    )
    file_storage_reserve_percent: float = Field(
        default=10.0, ge=0.0, le=100.0, description="Minimum percentage file storage reserve"
    )
    api_requests_reserve: int = Field(
        default=100, ge=0, description="Minimum absolute daily API requests reserve"
    )
    api_requests_reserve_percent: float = Field(
        default=5.0, ge=0.0, le=100.0, description="Minimum percentage daily API requests reserve"
    )
    warning_multiplier: float = Field(
        default=2.0, ge=1.0, description="Multiplier on reserve to determine warning threshold"
    )
    freshness_hours: float = Field(
        default=1.0, ge=0.1, description="Maximum age of limits measurement before recheck"
    )
    recheck_delay_seconds: int = Field(
        default=300, ge=1, description="Backoff delay in seconds after a blocked capacity check"
    )
    per_record_data_bytes_estimate: int = Field(
        default=2048, ge=1, description="Estimated byte consumption per synchronized row (for forecasting only)"
    )


class PortabilitySettings(ContractModel):
    """Settings controlling metadata retrieval, validation, and candidate data export."""

    export_root: str = Field(
        default="local_data/exports", description="Destination directory for completed exports"
    )
    staging_root: str = Field(
        default="local_data/staging/exports", description="Temporary staging directory during export"
    )
    batch_size: int = Field(
        default=100, ge=1, le=2000, description="Pagination batch size for SOQL query iteration"
    )
    freshness_hours: float = Field(
        default=24.0, ge=0.1, description="Freshness window in hours for considering an export valid"
    )
    require_company_closure: bool = Field(
        default=True, description="Enforce that every referenced Company lookup is exported and resolved"
    )
    export_field_history: bool = Field(
        default=True, description="Attempt querying Job__History if available and permitted"
    )
    max_retries: int = Field(
        default=3, ge=1, description="Maximum retry attempts for transient query failures"
    )
    capacity: CapacityPolicySettings = Field(
        default_factory=CapacityPolicySettings, description="Capacity evaluation policy"
    )


def load_portability_settings(path: Path | str | None = None) -> PortabilitySettings:
    """Load PortabilitySettings from a JSON configuration file or return default settings."""
    if path is None:
        return PortabilitySettings()

    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Portability configuration file not found: {p}")

    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return PortabilitySettings.model_validate(data)

