"""Delivery configuration settings (GEN-06-S01).

Configures:
- Target Salesforce org constraints.
- ContentVersion marker and hash field names.
- File upload ceilings, download ceilings, and call budgets.
- Retry backoff intervals and candidate access verification strategy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from job_automation.contracts.base import ContractModel


class DeliverySettings(ContractModel):
    """Runtime settings for Salesforce Files artifact delivery and review integration."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    expected_org_id: str = Field(
        default="00D000000000000EAA",
        min_length=15,
        max_length=18,
        description="Expected target Salesforce 15 or 18 character organization ID",
    )
    marker_field: str = Field(
        default="Description",
        description="Salesforce ContentVersion field storing the reconciliation marker",
    )
    hash_field: str = Field(
        default="Description",
        description="Salesforce ContentVersion field storing content hash claim",
    )
    max_file_size_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10 MB limit for base64 JSON upload
        gt=0,
        description="Maximum file size in bytes permitted for upload",
    )
    max_download_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        description="Maximum bytes allowed for integrity verification downloads",
    )
    max_query_candidates: int = Field(
        default=50,
        gt=0,
        description="Maximum results returned when querying by marker",
    )
    max_delivery_attempts: int = Field(
        default=5,
        ge=1,
        description="Maximum retries permitted for delivery of an artifact format",
    )
    initial_backoff_seconds: float = Field(
        default=1.0,
        ge=0.1,
        description="Initial exponential backoff delay in seconds",
    )
    max_backoff_seconds: float = Field(
        default=60.0,
        ge=1.0,
        description="Maximum backoff delay ceiling in seconds",
    )
    access_verification_method: Literal[
        "direct_download", "sharing_policy_check", "mock_verification"
    ] = Field(
        default="sharing_policy_check",
        description="Method used to certify candidate file accessibility",
    )
    review_route_template: str = Field(
        default="https://salesforce.com/lightning/r/Generation_Request__c/{salesforce_request_id}/view",
        description="Template for building candidate-accessible review route",
    )

