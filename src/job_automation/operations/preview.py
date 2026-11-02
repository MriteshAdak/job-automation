"""Reviewable cleanup preview generator (OPS-01-S03).

Generates immutable, fingerprint-bound CleanupPlan records without
performing any deletions or mutations.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from job_automation.operations.records import (
    CleanupPlan,
    OperationsSettings,
    RetentionInventory,
)
from job_automation.operations.retention import evaluate_retention
from job_automation.operations.settings import compute_policy_fingerprint
from job_automation.storage.engine import StorageEngine


def compute_plan_hash(
    store_fingerprint: str,
    policy_fingerprint: str,
    candidates: list[dict[str, Any]],
) -> str:
    """Compute deterministic hash of cleanup plan candidates and preflight fingerprints."""
    sorted_candidates = sorted(
        [
            f"{c['root_relative_path']}:{c['expected_hash']}:{c['size_bytes']}"
            for c in candidates
        ]
    )
    payload = f"{store_fingerprint};{policy_fingerprint};{','.join(sorted_candidates)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_cleanup_preview(
    inventory: RetentionInventory,
    settings: OperationsSettings,
    engine: StorageEngine | None = None,
    cutoff_time: datetime | None = None,
    expiry_hours: int = 24,
) -> CleanupPlan:
    """Produce an immutable CleanupPlan and persist it in operations repository if engine is provided."""
    now_dt = datetime.now(timezone.utc)
    cutoff = cutoff_time or now_dt
    expires_dt = now_dt + timedelta(hours=expiry_hours)

    candidates, prot_count, blocked_count, prot_by_class, est_reclaim = evaluate_retention(
        inventory=inventory,
        settings=settings,
        cutoff_time=cutoff,
    )

    policy_fp = compute_policy_fingerprint(settings)
    cand_dicts = [c.model_dump() for c in candidates]
    plan_hash = compute_plan_hash(inventory.store_fingerprint, policy_fp, cand_dicts)
    plan_id = uuid.uuid4()

    plan = CleanupPlan(
        plan_id=plan_id,
        created_at=now_dt,
        expires_at=expires_dt,
        store_fingerprint=inventory.store_fingerprint,
        policy_fingerprint=policy_fp,
        plan_hash=plan_hash,
        cutoff_time=cutoff,
        candidates=candidates,
        protected_items_count=prot_count,
        blocked_items_count=blocked_count,
        protected_by_class=prot_by_class,
        estimated_reclaim_bytes=est_reclaim,
        status="planned",
    )

    if engine is not None:
        engine.operations.save_cleanup_plan(
            plan_id=plan.plan_id,
            created_at=plan.created_at.isoformat(),
            expires_at=plan.expires_at.isoformat(),
            store_fingerprint=plan.store_fingerprint,
            policy_fingerprint=plan.policy_fingerprint,
            plan_hash=plan.plan_hash,
            status=plan.status,
            plan_json=plan.model_dump_json(),
        )

    return plan

