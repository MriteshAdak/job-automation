"""Unit tests for operations contract records and immutability (OPS-01-S01)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.operations.records import (
    BackupFileEntry,
    BackupManifest,
    BackupSettings,
    CapacityReport,
    CapacitySettings,
    CapacityStatus,
    CapacityVolumeReport,
    CleanupCandidate,
    CleanupPlan,
    CleanupResult,
    InventoryItem,
    ItemClass,
    MaintenanceReport,
    OperationStatus,
    OperationsSettings,
    ProtectionReason,
    RemoteCapacityObservation,
    RemoteCompleteness,
    RemoteRecoveryExport,
    RestorePlan,
    RestoreResult,
    RetentionInventory,
    RetentionSettings,
)


def test_operations_settings_defaults() -> None:
    settings = OperationsSettings()
    assert settings.schema_version == "1.0"
    assert settings.retention.enabled is False
    assert settings.retention.raw_payloads_days == 90
    assert settings.backup.keep_generations == 3
    assert settings.capacity.reserve_bytes == 1073741824
    assert settings.capacity.reserve_percent == 10.0


def test_operations_settings_immutability() -> None:
    settings = OperationsSettings()
    with pytest.raises(ValidationError):
        settings.retention = RetentionSettings(enabled=True)  # type: ignore


def test_retention_inventory_serialization() -> None:
    now_dt = datetime.now(timezone.utc)
    item = InventoryItem(
        item_id="raw/sample.json",
        root_relative_path="raw/sample.json",
        item_class=ItemClass.RAW_PAYLOAD,
        size_bytes=1024,
        content_hash="sha256:abc123",
        observed_at=now_dt,
        is_referenced=True,
        referencing_records=["raw_postings:provider/board/1"],
        is_protected=True,
        protection_reasons=[ProtectionReason.REFERENCED_BY_RECORD],
    )
    inv = RetentionInventory(
        data_root="C:/data",
        scanned_at=now_dt,
        store_fingerprint="fp123",
        total_files_count=1,
        total_files_bytes=1024,
        items=[item],
        table_counts={"raw_postings": 1},
        unknown_files=[],
        protection_summary={"referenced_by_record": 1},
    )
    json_str = inv.model_dump_json()
    reloaded = RetentionInventory.model_validate_json(json_str)
    assert reloaded.total_files_count == 1
    assert reloaded.items[0].content_hash == "sha256:abc123"
    assert reloaded.items[0].protection_reasons == [ProtectionReason.REFERENCED_BY_RECORD]


def test_cleanup_plan_and_result_contracts() -> None:
    now_dt = datetime.now(timezone.utc)
    candidate = CleanupCandidate(
        candidate_id="c1",
        root_relative_path="raw/old.json",
        item_class=ItemClass.RAW_PAYLOAD,
        size_bytes=500,
        expected_hash="sha256:deadbeef",
        age_days=100.0,
        cutoff_time=now_dt,
        reason="Unreferenced raw payload older than 90 days",
    )
    plan = CleanupPlan(
        created_at=now_dt,
        expires_at=now_dt,
        store_fingerprint="fp",
        policy_fingerprint="pfp",
        plan_hash="hash123",
        cutoff_time=now_dt,
        candidates=[candidate],
        protected_items_count=10,
        blocked_items_count=0,
        protected_by_class={"raw_payload": 10},
        estimated_reclaim_bytes=500,
    )
    assert plan.candidates[0].candidate_id == "c1"

    res = CleanupResult(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        applied_at=now_dt,
        status=OperationStatus.SUCCEEDED,
        attempted_count=1,
        deleted_count=1,
        skipped_count=0,
        failed_count=0,
        actual_reclaimed_bytes=500,
    )
    assert res.status == OperationStatus.SUCCEEDED


def test_backup_manifest_roundtrip() -> None:
    now_dt = datetime.now(timezone.utc)
    manifest = BackupManifest(
        created_at=now_dt,
        app_version="1.0.0",
        schema_version=9,
        migration_checksums={1: "abc", 9: "def"},
        local_cut_time=now_dt,
        source_data_root="C:/data",
        files=[
            BackupFileEntry(
                root_relative_path="database/job_automation.db",
                sha256="sha256:111",
                size_bytes=4096,
                item_class=ItemClass.DATABASE,
            )
        ],
        total_files_count=1,
        total_bytes=4096,
        completeness_status="complete_local",
    )
    json_bytes = manifest.model_dump_json()
    loaded = BackupManifest.model_validate_json(json_bytes)
    assert loaded.schema_version == 9
    assert loaded.files[0].root_relative_path == "database/job_automation.db"


def test_maintenance_report_contract() -> None:
    now_dt = datetime.now(timezone.utc)
    report = MaintenanceReport(
        operation_type="backup_create",
        started_at=now_dt,
        completed_at=now_dt,
        status=OperationStatus.SUCCEEDED,
        counts={"files_backed_up": 10},
        bytes_processed=50000,
        safe_next_action="Store backup on redundant offline media",
        integrity_verified=True,
        restore_tested=False,
    )
    assert report.integrity_verified is True
    assert report.restore_tested is False

