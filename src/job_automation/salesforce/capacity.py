"""Salesforce organization capacity checks and operational headroom evaluation (SF-04-S01).

Enforces:
- Authenticated, dated capacity observations bound to target org ID and API version.
- Precise mapping of LimitsResult attributes and raw_limits categories (DataStorageMB, FileStorageMB, DailyApiRequests).
- used = max - remaining calculation only for valid, non-negative, consistent values.
- Zero-maximum and missing categories treated explicitly as unknown (never divided by zero or assumed unlimited).
- Operation-specific decisions (publication, file_upload, export_read) with configured reserves and cost forecasting.
- Non-blocking behavior for local operations during remote outages.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import LimitsRequest, LimitsResult
from job_automation.salesforce.portability_records import (
    CapacityDecision,
    CapacityObservation,
    CapacityResource,
)
from job_automation.salesforce.portability_settings import CapacityPolicySettings

logger = logging.getLogger(__name__)


def parse_resource_metrics(
    name: str,
    unit: str,
    max_val: Any,
    remaining_val: Any,
    reserve_abs: float,
    reserve_pct: float,
    warning_multiplier: float,
) -> CapacityResource:
    """Parse, validate, and evaluate headroom for a single named resource.

    Zero maximum, null values, or negative/inconsistent counts produce status='unknown'.
    """
    if max_val is None or remaining_val is None:
        return CapacityResource(
            name=name,
            unit=unit,
            max_value=None,
            remaining_value=None,
            used_value=None,
            percent_used=None,
            status="unknown",
            reason=f"Resource '{name}' is not present or returned null",
        )

    try:
        m = float(max_val)
        r = float(remaining_val)
    except (ValueError, TypeError):
        return CapacityResource(
            name=name,
            unit=unit,
            max_value=None,
            remaining_value=None,
            used_value=None,
            percent_used=None,
            status="unknown",
            reason=f"Resource '{name}' contains non-numeric values ({max_val}, {remaining_val})",
        )

    if m <= 0:
        # Zero or negative max is invalid/unknown allocation; prevent division by zero
        return CapacityResource(
            name=name,
            unit=unit,
            max_value=m,
            remaining_value=r,
            used_value=None,
            percent_used=None,
            status="unknown",
            reason=f"Resource '{name}' maximum allocation is zero or negative ({m})",
        )

    if r < 0 or r > m:
        return CapacityResource(
            name=name,
            unit=unit,
            max_value=m,
            remaining_value=r,
            used_value=None,
            percent_used=None,
            status="unknown",
            reason=f"Resource '{name}' remaining ({r}) is invalid or exceeds maximum ({m})",
        )

    used = m - r
    pct_used = (used / m) * 100.0

    # Effective reserve: greater of absolute reserve and percentage reserve
    pct_reserve_val = m * (reserve_pct / 100.0)
    effective_reserve = max(reserve_abs, pct_reserve_val)
    warning_threshold = effective_reserve * warning_multiplier

    if r < effective_reserve:
        status = "blocked"
        reason = (
            f"Remaining {r:g} {unit} is below required reserve of {effective_reserve:g} {unit} "
            f"({pct_used:.1f}% used)"
        )
    elif r < warning_threshold:
        status = "warning"
        reason = (
            f"Remaining {r:g} {unit} is near reserve threshold ({effective_reserve:g} {unit}) "
            f"({pct_used:.1f}% used)"
        )
    else:
        status = "ok"
        reason = f"Headroom healthy ({r:g} {unit} remaining, {pct_used:.1f}% used)"

    return CapacityResource(
        name=name,
        unit=unit,
        max_value=m,
        remaining_value=r,
        used_value=used,
        percent_used=pct_used,
        status=status,
        reason=reason,
    )


def observe_capacity_from_limits(
    limits_result: LimitsResult,
    org_id: str,
    api_version: str,
    settings: CapacityPolicySettings,
    measured_at: datetime | None = None,
) -> CapacityObservation:
    """Build a CapacityObservation from a Gateway LimitsResult."""
    now_dt = measured_at or datetime.now(timezone.utc)
    resources: dict[str, CapacityResource] = {}

    # 1. Daily API Requests
    api_max = limits_result.daily_api_requests_max
    api_rem = limits_result.daily_api_requests_remaining
    if api_max is None and "DailyApiRequests" in limits_result.raw_limits:
        api_max = limits_result.raw_limits["DailyApiRequests"].get("Max")
        api_rem = limits_result.raw_limits["DailyApiRequests"].get("Remaining")

    resources["daily_api_requests"] = parse_resource_metrics(
        name="daily_api_requests",
        unit="requests",
        max_val=api_max,
        remaining_val=api_rem,
        reserve_abs=float(settings.api_requests_reserve),
        reserve_pct=settings.api_requests_reserve_percent,
        warning_multiplier=settings.warning_multiplier,
    )

    # 2. Data Storage MB
    data_entry = limits_result.raw_limits.get("DataStorageMB", {})
    resources["data_storage_mb"] = parse_resource_metrics(
        name="data_storage_mb",
        unit="MB",
        max_val=data_entry.get("Max"),
        remaining_val=data_entry.get("Remaining"),
        reserve_abs=settings.data_storage_reserve_mb,
        reserve_pct=settings.data_storage_reserve_percent,
        warning_multiplier=settings.warning_multiplier,
    )

    # 3. File Storage MB
    file_entry = limits_result.raw_limits.get("FileStorageMB", {})
    resources["file_storage_mb"] = parse_resource_metrics(
        name="file_storage_mb",
        unit="MB",
        max_val=file_entry.get("Max"),
        remaining_val=file_entry.get("Remaining"),
        reserve_abs=settings.file_storage_reserve_mb,
        reserve_pct=settings.file_storage_reserve_percent,
        warning_multiplier=settings.warning_multiplier,
    )

    # Evaluate overall status across core resources
    core_statuses = [
        resources["daily_api_requests"].status,
        resources["data_storage_mb"].status,
        resources["file_storage_mb"].status,
    ]

    if "blocked" in core_statuses:
        overall = "blocked"
    elif "unknown" in core_statuses:
        overall = "unknown"
    elif "warning" in core_statuses:
        overall = "warning"
    else:
        overall = "ok"

    return CapacityObservation(
        org_id=org_id,
        api_version=api_version,
        measured_at=now_dt,
        evidence_source="rest_limits",
        resources=resources,
        overall_status=overall,
        notes=f"Observed {len(resources)} resources via Salesforce REST limits",
    )


def query_and_observe_capacity(
    gateway: SalesforceGatewayV2,
    settings: CapacityPolicySettings,
    expected_org_id: str,
    api_version: str,
) -> tuple[CapacityObservation, list[ClassifiedError]]:
    """Query Salesforce gateway for limits and construct an authenticated CapacityObservation."""
    now_dt = datetime.now(timezone.utc)
    issues: list[ClassifiedError] = []

    req = LimitsRequest()
    res = gateway.get_limits(req)

    if res.is_failure or res.value is None:
        err = res.failure.error if res.failure else ClassifiedError(
            category=ErrorCategory.CAPACITY,
            message="Salesforce limits request returned unknown failure",
            recoverable=True,
        )
        issues.append(err)
        obs = CapacityObservation(
            org_id=expected_org_id,
            api_version=api_version,
            measured_at=now_dt,
            evidence_source="rest_limits_failed",
            resources={},
            overall_status="unknown",
            notes=f"Limits query failed: {err.message}",
        )
        return obs, issues

    obs = observe_capacity_from_limits(
        limits_result=res.value,
        org_id=expected_org_id,
        api_version=api_version,
        settings=settings,
        measured_at=now_dt,
    )
    return obs, issues


def evaluate_capacity_decision(
    observation: CapacityObservation,
    operation_kind: str,
    settings: CapacityPolicySettings,
    planned_records: int = 0,
    planned_files_mb: float = 0.0,
    planned_calls: int = 1,
    current_time: datetime | None = None,
) -> CapacityDecision:
    """Evaluate whether a specific operation is permitted based on capacity observation and policy."""
    now_dt = current_time or datetime.now(timezone.utc)
    age_hours = (now_dt - observation.measured_at).total_seconds() / 3600.0

    # Check evidence freshness
    if age_hours > settings.freshness_hours:
        return CapacityDecision(
            operation_kind=operation_kind,
            status="unknown",
            allowed=False,
            reason=f"Capacity observation is stale ({age_hours:.1f} hours old, max allowed {settings.freshness_hours}h)",
            recheck_after_seconds=settings.recheck_delay_seconds,
            estimated_cost={"freshness_age_hours": age_hours},
        )

    # API calls are consumed by every remote operation
    api_res = observation.resources.get("daily_api_requests")
    if api_res is None or api_res.status == "unknown":
        return CapacityDecision(
            operation_kind=operation_kind,
            status="unknown",
            allowed=False,
            reason="Daily API request limit observation is missing or unknown",
            recheck_after_seconds=settings.recheck_delay_seconds,
        )

    if api_res.status == "blocked" or (
        api_res.remaining_value is not None and api_res.remaining_value < planned_calls
    ):
        return CapacityDecision(
            operation_kind=operation_kind,
            status="blocked",
            allowed=False,
            reason=f"Daily API request allowance exhausted or insufficient for planned {planned_calls} calls",
            recheck_after_seconds=settings.recheck_delay_seconds,
            estimated_cost={"planned_calls": planned_calls, "api_remaining": api_res.remaining_value},
        )

    # Operation-specific checks
    if operation_kind == "publication":
        # Requires data storage headroom
        data_res = observation.resources.get("data_storage_mb")
        if data_res is None or data_res.status == "unknown":
            return CapacityDecision(
                operation_kind=operation_kind,
                status="unknown",
                allowed=False,
                reason="Data storage limit observation is missing or unknown",
                recheck_after_seconds=settings.recheck_delay_seconds,
            )

        estimated_data_mb = (planned_records * settings.per_record_data_bytes_estimate) / (1024 * 1024)
        if data_res.status == "blocked" or (
            data_res.remaining_value is not None and data_res.remaining_value < estimated_data_mb
        ):
            return CapacityDecision(
                operation_kind=operation_kind,
                status="blocked",
                allowed=False,
                reason=(
                    f"Data storage is blocked or insufficient ({data_res.remaining_value} MB remaining, "
                    f"planned {estimated_data_mb:.4f} MB for {planned_records} records)"
                ),
                recheck_after_seconds=settings.recheck_delay_seconds,
                estimated_cost={"planned_records": planned_records, "estimated_mb": estimated_data_mb},
            )

        status = "warning" if (data_res.status == "warning" or api_res.status == "warning") else "ok"
        return CapacityDecision(
            operation_kind=operation_kind,
            status=status,
            allowed=True,
            reason="Headroom sufficient for publication",
            estimated_cost={"planned_records": planned_records, "estimated_mb": estimated_data_mb},
        )

    elif operation_kind == "file_upload":
        # Requires file storage headroom
        file_res = observation.resources.get("file_storage_mb")
        if file_res is None or file_res.status == "unknown":
            return CapacityDecision(
                operation_kind=operation_kind,
                status="unknown",
                allowed=False,
                reason="File storage limit observation is missing or unknown",
                recheck_after_seconds=settings.recheck_delay_seconds,
            )

        if file_res.status == "blocked" or (
            file_res.remaining_value is not None and file_res.remaining_value < planned_files_mb
        ):
            return CapacityDecision(
                operation_kind=operation_kind,
                status="blocked",
                allowed=False,
                reason=(
                    f"File storage is blocked or insufficient ({file_res.remaining_value} MB remaining, "
                    f"planned upload {planned_files_mb:.2f} MB)"
                ),
                recheck_after_seconds=settings.recheck_delay_seconds,
                estimated_cost={"planned_files_mb": planned_files_mb},
            )

        status = "warning" if (file_res.status == "warning" or api_res.status == "warning") else "ok"
        return CapacityDecision(
            operation_kind=operation_kind,
            status=status,
            allowed=True,
            reason="Headroom sufficient for file upload",
            estimated_cost={"planned_files_mb": planned_files_mb},
        )

    elif operation_kind == "export_read":
        # Read-only export does NOT write to DataStorage or FileStorage; requires only API calls
        status = "warning" if api_res.status == "warning" else "ok"
        return CapacityDecision(
            operation_kind=operation_kind,
            status=status,
            allowed=True,
            reason=f"API allowance sufficient for export read operations ({planned_calls} calls budgeted)",
            estimated_cost={"planned_calls": planned_calls},
        )

    else:
        return CapacityDecision(
            operation_kind=operation_kind,
            status="unknown",
            allowed=False,
            reason=f"Unrecognized operation kind '{operation_kind}'",
            recheck_after_seconds=settings.recheck_delay_seconds,
        )

