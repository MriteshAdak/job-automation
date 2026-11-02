"""Unit tests for retention policy evaluation and protection rules (OPS-01-S03)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from job_automation.operations.records import (
    InventoryItem,
    ItemClass,
    OperationsSettings,
    ProtectionReason,
    RetentionInventory,
)
from job_automation.operations.retention import evaluate_retention


def test_retention_disabled_protects_all_items() -> None:
    now_dt = datetime.now(timezone.utc)
    old_dt = now_dt - timedelta(days=200)

    item = InventoryItem(
        item_id="raw/old.json",
        root_relative_path="raw/old.json",
        item_class=ItemClass.RAW_PAYLOAD,
        size_bytes=1000,
        content_hash="sha256:111",
        observed_at=old_dt,
        is_referenced=False,
        referencing_records=[],
        is_protected=False,
        protection_reasons=[],
    )

    inv = RetentionInventory(
        data_root="C:/data",
        scanned_at=now_dt,
        store_fingerprint="fp",
        total_files_count=1,
        total_files_bytes=1000,
        items=[item],
    )

    # settings.retention.enabled is False by default
    settings = OperationsSettings()
    candidates, prot_count, blocked_count, prot_by_class, est_reclaim = evaluate_retention(
        inventory=inv,
        settings=settings,
        cutoff_time=now_dt,
    )

    assert len(candidates) == 0
    assert prot_count == 1
    assert est_reclaim == 0


def test_unreferenced_old_payload_is_eligible_when_enabled() -> None:
    now_dt = datetime.now(timezone.utc)
    old_dt = now_dt - timedelta(days=120)  # > 90 days

    item = InventoryItem(
        item_id="raw/old.json",
        root_relative_path="raw/old.json",
        item_class=ItemClass.RAW_PAYLOAD,
        size_bytes=1000,
        content_hash="sha256:111",
        observed_at=old_dt,
        is_referenced=False,
        referencing_records=[],
        is_protected=False,
        protection_reasons=[],
    )

    inv = RetentionInventory(
        data_root="C:/data",
        scanned_at=now_dt,
        store_fingerprint="fp",
        total_files_count=1,
        total_files_bytes=1000,
        items=[item],
    )

    settings = OperationsSettings(retention={"enabled": True, "raw_payloads_days": 90})
    candidates, prot_count, blocked_count, prot_by_class, est_reclaim = evaluate_retention(
        inventory=inv,
        settings=settings,
        cutoff_time=now_dt,
    )

    assert len(candidates) == 1
    assert candidates[0].candidate_id == "raw/old.json"
    assert est_reclaim == 1000
    assert prot_count == 0


def test_referenced_old_payload_remains_protected() -> None:
    now_dt = datetime.now(timezone.utc)
    old_dt = now_dt - timedelta(days=300)

    item = InventoryItem(
        item_id="raw/cited.json",
        root_relative_path="raw/cited.json",
        item_class=ItemClass.RAW_PAYLOAD,
        size_bytes=1000,
        content_hash="sha256:111",
        observed_at=old_dt,
        is_referenced=True,
        referencing_records=["raw_postings:arbeitnow/default/1"],
        is_protected=True,
        protection_reasons=[ProtectionReason.REFERENCED_BY_RECORD],
    )

    inv = RetentionInventory(
        data_root="C:/data",
        scanned_at=now_dt,
        store_fingerprint="fp",
        total_files_count=1,
        total_files_bytes=1000,
        items=[item],
    )

    settings = OperationsSettings(retention={"enabled": True, "raw_payloads_days": 90})
    candidates, prot_count, blocked_count, prot_by_class, est_reclaim = evaluate_retention(
        inventory=inv,
        settings=settings,
        cutoff_time=now_dt,
    )

    assert len(candidates) == 0
    assert prot_count == 1


def test_source_override_retention() -> None:
    now_dt = datetime.now(timezone.utc)
    old_40d = now_dt - timedelta(days=40)

    item = InventoryItem(
        item_id="raw/short_lived/doc.json",
        root_relative_path="raw/short_lived/doc.json",
        item_class=ItemClass.RAW_PAYLOAD,
        size_bytes=500,
        content_hash="sha256:111",
        observed_at=old_40d,
        is_referenced=False,
        referencing_records=[],
        is_protected=False,
        protection_reasons=[],
    )

    inv = RetentionInventory(
        data_root="C:/data",
        scanned_at=now_dt,
        store_fingerprint="fp",
        total_files_count=1,
        total_files_bytes=500,
        items=[item],
    )

    # Default is 90 days, but short_lived source override is 30 days
    settings = OperationsSettings(
        retention={
            "enabled": True,
            "raw_payloads_days": 90,
            "source_overrides": {"short_lived": 30},
        }
    )
    candidates, prot_count, blocked_count, prot_by_class, est_reclaim = evaluate_retention(
        inventory=inv,
        settings=settings,
        cutoff_time=now_dt,
    )

    assert len(candidates) == 1
    assert candidates[0].size_bytes == 500

