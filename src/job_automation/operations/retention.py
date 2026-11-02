"""Retention policy evaluation and protection closure (OPS-01-S03).

Enforces:
- Protection closure precedes any age-based retention rules.
- Master retention disable: if settings.retention.enabled is False, zero files are eligible.
- Deterministic single UTC cutoff time for age calculations.
- Source-specific retention overrides.
- Retaining compact durable database records indefinitely in OPS v1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from job_automation.operations.records import (
    CleanupCandidate,
    InventoryItem,
    ItemClass,
    OperationsSettings,
    ProtectionReason,
    RetentionInventory,
)


def evaluate_retention(
    inventory: RetentionInventory,
    settings: OperationsSettings,
    cutoff_time: datetime | None = None,
) -> tuple[list[CleanupCandidate], int, int, dict[str, int], int]:
    """Evaluate inventory items against retention policy.

    Returns:
        (candidates, protected_count, blocked_count, protected_by_class, estimated_reclaim_bytes)
    """
    cutoff = cutoff_time or datetime.now(timezone.utc)
    candidates: list[CleanupCandidate] = []

    protected_count = 0
    blocked_count = 0
    protected_by_class: dict[str, int] = {}
    estimated_reclaim = 0

    for item in inventory.items:
        # Check explicit protection first
        is_item_protected = item.is_protected
        item_class_str = item.item_class.value

        # Unknown format/schema is always blocked
        if item.item_class == ItemClass.UNKNOWN or ProtectionReason.UNKNOWN_SCHEMA_OR_FORMAT in item.protection_reasons:
            blocked_count += 1
            protected_count += 1
            protected_by_class[item_class_str] = protected_by_class.get(item_class_str, 0) + 1
            continue

        # If retention is disabled globally, nothing is eligible
        if not settings.retention.enabled:
            protected_count += 1
            protected_by_class[item_class_str] = protected_by_class.get(item_class_str, 0) + 1
            continue

        if is_item_protected:
            protected_count += 1
            protected_by_class[item_class_str] = protected_by_class.get(item_class_str, 0) + 1
            continue

        # Calculate age from cutoff
        age_seconds = (cutoff - item.observed_at).total_seconds()
        age_days = max(0.0, age_seconds / 86400.0)

        is_eligible = False
        reason = ""

        if item.item_class == ItemClass.RAW_PAYLOAD:
            # Check for source override
            allowed_days = settings.retention.raw_payloads_days
            for src_name, override_days in settings.retention.source_overrides.items():
                if f"raw/{src_name}/" in item.root_relative_path:
                    allowed_days = override_days
                    break

            if age_days >= allowed_days:
                is_eligible = True
                reason = f"Unreferenced raw payload age ({age_days:.1f}d) exceeds policy threshold ({allowed_days}d)"
            else:
                reason = f"Unreferenced raw payload within retention period ({age_days:.1f}d < {allowed_days}d)"

        elif item.item_class == ItemClass.LOG:
            if age_days >= settings.retention.logs_days:
                is_eligible = True
                reason = f"Closed log file age ({age_days:.1f}d) exceeds threshold ({settings.retention.logs_days}d)"
            else:
                reason = f"Log file within retention period ({age_days:.1f}d < {settings.retention.logs_days}d)"

        elif item.item_class == ItemClass.CONTEXT_INDEX:
            # Retired unpinned index generations
            is_eligible = True
            reason = "Retired unpinned index payload beyond retention allowance"

        if is_eligible:
            candidates.append(
                CleanupCandidate(
                    candidate_id=item.item_id,
                    root_relative_path=item.root_relative_path,
                    item_class=item.item_class,
                    size_bytes=item.size_bytes,
                    expected_hash=item.content_hash,
                    age_days=age_days,
                    cutoff_time=cutoff,
                    reason=reason,
                )
            )
            estimated_reclaim += item.size_bytes
        else:
            protected_count += 1
            protected_by_class[item_class_str] = protected_by_class.get(item_class_str, 0) + 1

    return candidates, protected_count, blocked_count, protected_by_class, estimated_reclaim

