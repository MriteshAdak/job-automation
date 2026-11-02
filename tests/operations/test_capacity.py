"""Unit tests for storage capacity checks and threshold enforcement (OPS-01-S02)."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.operations.capacity import check_capacity, measure_volume_capacity
from job_automation.operations.records import (
    CapacitySettings,
    CapacityStatus,
    OperationsSettings,
)


def test_measure_volume_capacity_normal(tmp_path: Path) -> None:
    settings = CapacitySettings(reserve_bytes=1000, reserve_percent=1.0)
    rep, issues = measure_volume_capacity(
        target_path=tmp_path,
        required_bytes=500,
        settings=settings,
    )
    assert rep.status in (CapacityStatus.OK, CapacityStatus.WARNING)
    assert rep.total_bytes > 0
    assert rep.free_bytes > 0
    assert len(issues) == 0


def test_measure_volume_capacity_blocked(tmp_path: Path) -> None:
    # Set an impossible required_bytes
    settings = CapacitySettings(reserve_bytes=1000, reserve_percent=1.0)
    rep, issues = measure_volume_capacity(
        target_path=tmp_path,
        required_bytes=10**18,  # Exceeds volume capacity
        settings=settings,
    )
    assert rep.status == CapacityStatus.BLOCKED
    assert len(issues) == 1
    assert issues[0].category == ErrorCategory.CAPACITY


def test_measure_volume_capacity_unmounted() -> None:
    settings = CapacitySettings()
    # Non-existent drive or unreachable path
    rep, issues = measure_volume_capacity(
        target_path="Z:\\NonExistentDrive\\JobData",
        required_bytes=100,
        settings=settings,
    )
    assert rep.status == CapacityStatus.UNKNOWN
    assert len(issues) == 1
    assert issues[0].category == ErrorCategory.CAPACITY


def test_check_capacity_same_disk_deduplication(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    settings = OperationsSettings()
    report = check_capacity(
        settings=settings,
        source_root=src_dir,
        destination_path=dst_dir,
        estimated_source_required_bytes=1000,
        estimated_destination_required_bytes=2000,
    )

    assert report.source_volume is not None
    assert report.destination_volume is not None
    assert report.destination_volume.is_same_disk is True
    # In same-disk case, destination required bytes includes source required bytes
    assert report.destination_volume.required_bytes == 3000
    assert report.remote_capacity.status == "unknown"

