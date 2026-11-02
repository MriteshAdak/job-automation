"""Storage capacity monitoring for local volumes and remote service quotas (OPS-01-S02).

Measures:
- Source deployment data root volume
- Backup destination volume (accounting for same-disk deduplication)
- Restore staging / temporary volumes
- Remote Salesforce quota observation via SF-04 boundary (or unknown status)
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.primitives import UtcDatetime
from job_automation.operations.paths import is_same_physical_device
from job_automation.operations.records import (
    CapacityReport,
    CapacitySettings,
    CapacityStatus,
    CapacityVolumeReport,
    OperationsSettings,
    RemoteCapacityObservation,
)

logger = logging.getLogger(__name__)


def measure_volume_capacity(
    target_path: Path | str,
    required_bytes: int,
    settings: CapacitySettings,
    reference_path: Path | str | None = None,
) -> tuple[CapacityVolumeReport, list[ClassifiedError]]:
    """Measure disk capacity for a given path and evaluate against configured reserves."""
    path = Path(target_path).resolve()
    issues: list[ClassifiedError] = []

    # If directory doesn't exist, check parent that exists
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent

    if not probe.exists():
        # Unmounted or unreachable path
        issue = ClassifiedError(
            category=ErrorCategory.CAPACITY,
            message=f"Storage volume for '{target_path}' is unmounted or unreachable",
            recoverable=False,
            details={"target_path": str(target_path)},
        )
        return (
            CapacityVolumeReport(
                volume_path=str(path),
                device_id="unknown",
                total_bytes=0,
                used_bytes=0,
                free_bytes=0,
                required_bytes=required_bytes,
                reserve_bytes=settings.reserve_bytes,
                status=CapacityStatus.UNKNOWN,
                is_same_disk=False,
            ),
            [issue],
        )

    try:
        usage = shutil.disk_usage(str(probe))
        total_b = usage.total
        free_b = usage.free
        used_b = usage.used
    except (OSError, PermissionError) as exc:
        issue = ClassifiedError(
            category=ErrorCategory.CAPACITY,
            message=f"Failed to read disk usage for '{target_path}': {exc}",
            recoverable=False,
            details={"target_path": str(target_path), "error": str(exc)},
        )
        return (
            CapacityVolumeReport(
                volume_path=str(path),
                device_id="unreadable",
                total_bytes=0,
                used_bytes=0,
                free_bytes=0,
                required_bytes=required_bytes,
                reserve_bytes=settings.reserve_bytes,
                status=CapacityStatus.UNKNOWN,
                is_same_disk=False,
            ),
            [issue],
        )

    # Check same disk relative to reference
    is_same = False
    dev_desc = "volume"
    if reference_path is not None:
        is_same, dev_desc = is_same_physical_device(path, reference_path)

    # Reserve calculation: greater of reserve_bytes and reserve_percent of total
    percent_reserve = int(total_b * (settings.reserve_percent / 100.0))
    effective_reserve = max(settings.reserve_bytes, percent_reserve)

    post_op_free = free_b - required_bytes
    warning_threshold = int(effective_reserve * settings.warning_multiplier)

    if post_op_free < effective_reserve:
        status = CapacityStatus.BLOCKED
        issues.append(
            ClassifiedError(
                category=ErrorCategory.CAPACITY,
                message=(
                    f"Storage capacity BLOCKED on '{path}': predicted free space ({post_op_free} bytes) "
                    f"falls below required reserve ({effective_reserve} bytes)."
                ),
                recoverable=False,
                details={
                    "path": str(path),
                    "free_bytes": free_b,
                    "required_bytes": required_bytes,
                    "predicted_free": post_op_free,
                    "reserve_bytes": effective_reserve,
                },
            )
        )
    elif post_op_free < warning_threshold:
        status = CapacityStatus.WARNING
    else:
        status = CapacityStatus.OK

    report = CapacityVolumeReport(
        volume_path=str(path),
        device_id=dev_desc,
        total_bytes=total_b,
        used_bytes=used_b,
        free_bytes=free_b,
        required_bytes=required_bytes,
        reserve_bytes=effective_reserve,
        status=status,
        is_same_disk=is_same,
    )
    return report, issues


def check_capacity(
    settings: OperationsSettings,
    source_root: Path | str,
    destination_path: Path | str | None = None,
    staging_path: Path | str | None = None,
    estimated_source_required_bytes: int = 0,
    estimated_destination_required_bytes: int = 0,
    estimated_staging_required_bytes: int = 0,
    remote_client: Any | None = None,
) -> CapacityReport:
    """Consolidated check of source, destination, staging volumes and remote limits."""
    now_dt = datetime.now(timezone.utc)
    all_issues: list[ClassifiedError] = []

    # 1. Source volume
    src_rep, src_issues = measure_volume_capacity(
        target_path=source_root,
        required_bytes=estimated_source_required_bytes,
        settings=settings.capacity,
    )
    all_issues.extend(src_issues)

    # 2. Destination volume (if specified)
    dst_rep: CapacityVolumeReport | None = None
    if destination_path is not None:
        # If destination is on same physical device as source, add source required bytes
        is_same, _ = is_same_physical_device(destination_path, source_root)
        eff_dst_req = estimated_destination_required_bytes
        if is_same:
            eff_dst_req += estimated_source_required_bytes

        dst_rep, dst_issues = measure_volume_capacity(
            target_path=destination_path,
            required_bytes=eff_dst_req,
            settings=settings.capacity,
            reference_path=source_root,
        )
        all_issues.extend(dst_issues)

    # 3. Staging volume (if specified)
    stg_rep: CapacityVolumeReport | None = None
    if staging_path is not None:
        stg_rep, stg_issues = measure_volume_capacity(
            target_path=staging_path,
            required_bytes=estimated_staging_required_bytes,
            settings=settings.capacity,
            reference_path=source_root,
        )
        all_issues.extend(stg_issues)

    # 4. Remote capacity (SF-04)
    remote_obs: RemoteCapacityObservation
    if remote_client is not None and hasattr(remote_client, "get_limits"):
        try:
            from job_automation.contracts.salesforce import LimitsRequest
            try:
                res = remote_client.get_limits(LimitsRequest())
            except TypeError:
                res = remote_client.get_limits()

            if hasattr(res, "is_success") and res.is_success and res.value:
                val = res.value
                api_max = getattr(val, "daily_api_requests_max", None)
                api_rem = getattr(val, "daily_api_requests_remaining", None)
                raw = getattr(val, "raw_limits", {}) or {}

                if api_max is None and "DailyApiRequests" in raw:
                    api_max = raw["DailyApiRequests"].get("Max")
                    api_rem = raw["DailyApiRequests"].get("Remaining")

                api_used = (
                    (api_max - api_rem)
                    if (api_max is not None and api_rem is not None and api_rem <= api_max)
                    else None
                )

                data_entry = raw.get("DataStorageMB", {})
                data_max = data_entry.get("Max")
                data_rem = data_entry.get("Remaining")
                data_used = (
                    (data_max - data_rem)
                    if (data_max is not None and data_rem is not None and data_rem <= data_max)
                    else None
                )

                file_entry = raw.get("FileStorageMB", {})
                file_max = file_entry.get("Max")
                file_rem = file_entry.get("Remaining")
                file_used = (
                    (file_max - file_rem)
                    if (file_max is not None and file_rem is not None and file_rem <= file_max)
                    else None
                )

                # Evaluate remote status
                if (api_rem is not None and api_rem <= 0) or (data_rem is not None and data_rem <= 0) or (file_rem is not None and file_rem <= 0):
                    rem_status = "blocked"
                elif (
                    (api_max is not None and api_rem is not None and api_rem < api_max * 0.1)
                    or (data_max is not None and data_rem is not None and data_rem < data_max * 0.1)
                    or (file_max is not None and file_rem is not None and file_rem < file_max * 0.1)
                ):
                    rem_status = "warning"
                elif api_max is None and data_max is None and file_max is None:
                    rem_status = "unknown"
                else:
                    rem_status = "ok"

                remote_obs = RemoteCapacityObservation(
                    source="SF-04",
                    status=rem_status,
                    measured_at=now_dt,
                    api_limit=api_max,
                    api_used=api_used,
                    data_limit_mb=float(data_max) if data_max is not None else None,
                    data_used_mb=float(data_used) if data_used is not None else None,
                    file_limit_mb=float(file_max) if file_max is not None else None,
                    file_used_mb=float(file_used) if file_used is not None else None,
                    notes=f"Live limits queried via Salesforce client (status={rem_status})",
                )
            else:
                remote_obs = RemoteCapacityObservation(
                    source="SF-04",
                    status="unknown",
                    notes="Remote limits query returned failure; SF-04 export pending",
                )
        except Exception as exc:
            remote_obs = RemoteCapacityObservation(
                source="SF-04",
                status="unknown",
                notes=f"Remote limits query error: {exc}",
            )
    else:
        remote_obs = RemoteCapacityObservation(
            source="SF-04",
            status="unknown",
            notes="Remote capacity unknown: SF-04 handoff absent",
        )

    # Overall status
    statuses = [src_rep.status]
    if dst_rep:
        statuses.append(dst_rep.status)
    if stg_rep:
        statuses.append(stg_rep.status)

    if any(s in (CapacityStatus.BLOCKED, CapacityStatus.UNKNOWN) for s in statuses):
        overall = CapacityStatus.BLOCKED
    elif any(s == CapacityStatus.WARNING for s in statuses):
        overall = CapacityStatus.WARNING
    else:
        overall = CapacityStatus.OK

    return CapacityReport(
        report_id=uuid.uuid4(),
        measured_at=now_dt,
        overall_status=overall,
        source_volume=src_rep,
        destination_volume=dst_rep,
        staging_volume=stg_rep,
        remote_capacity=remote_obs,
        issues=all_issues,
    )
