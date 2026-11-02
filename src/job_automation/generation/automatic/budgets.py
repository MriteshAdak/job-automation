"""Budget and volume quota management for AUTO-02.

Enforces:
- Counting logical document requests (CV + Cover Letter = 2 units, regardless of file formats).
- Applying all limits together under transaction:
  * per-run limit (max_requests_per_run)
  * rolling-window limit (max_requests_per_window over window_hours)
  * outstanding limit (max_outstanding_requests)
  * per-job limit (max_requests_per_job)
- Bundle atomicity: candidate's selected document variants are reserved together;
  insufficient capacity defers the whole bundle rather than silently dropping a variant.
- Deterministic candidate ranking:
  1. Descending relevance score
  2. Ascending canonical job ID string (stable tie-breaker)
  3. Configured document variant order
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
)
from job_automation.storage.engine import StorageEngine


class QuotaCheckResult:
    """Result of quota capacity evaluation for a document request bundle."""

    def __init__(
        self,
        allowed: bool,
        reason: str | None = None,
        quota_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.quota_snapshot = quota_snapshot or {}


class BudgetManager:
    """Evaluates and enforces volume quotas across runs, windows, and jobs."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def rank_candidates(
        self,
        candidates: list[AutomaticDraftCandidate],
    ) -> list[AutomaticDraftCandidate]:
        """Rank qualifying candidates deterministically by score descending, then canonical_job_id."""
        return sorted(
            candidates,
            key=lambda c: (
                -(c.relevance_score if c.relevance_score is not None else -1.0),
                str(c.canonical_job_id),
            ),
        )

    def check_bundle_quota(
        self,
        candidate: AutomaticDraftCandidate,
        policy: AutomaticDraftPolicy,
        bundle_units: int,
        evaluation_run_id: uuid.UUID,
        now: datetime | None = None,
    ) -> QuotaCheckResult:
        """Check whether sufficient capacity exists across all volume limits for a document bundle."""
        now_utc = now or datetime.now(timezone.utc)
        limits = policy.volume_limits

        # 1. Per-run count
        current_run_count = self.engine.automatic_drafts.count_reservations_for_run(evaluation_run_id)
        if current_run_count + bundle_units > limits.max_requests_per_run:
            snapshot = self._build_snapshot(current_run_count, bundle_units, limits.max_requests_per_run, "run")
            return QuotaCheckResult(
                allowed=False,
                reason=f"Per-run limit exceeded: {current_run_count} + {bundle_units} > {limits.max_requests_per_run}",
                quota_snapshot=snapshot,
            )

        # 2. Rolling window count
        window_start = now_utc - timedelta(hours=limits.window_hours)
        current_window_count = self.engine.automatic_drafts.count_reservations_in_window(
            candidate_id=candidate.candidate_id,
            org_id=candidate.salesforce_org_id,
            since_utc=window_start,
        )
        if current_window_count + bundle_units > limits.max_requests_per_window:
            snapshot = self._build_snapshot(current_window_count, bundle_units, limits.max_requests_per_window, "window")
            return QuotaCheckResult(
                allowed=False,
                reason=f"Rolling window limit exceeded: {current_window_count} + {bundle_units} > {limits.max_requests_per_window}",
                quota_snapshot=snapshot,
            )

        # 3. Total outstanding count
        current_outstanding = self.engine.automatic_drafts.count_outstanding_reservations(
            candidate_id=candidate.candidate_id,
            org_id=candidate.salesforce_org_id,
        )
        if current_outstanding + bundle_units > limits.max_outstanding_requests:
            snapshot = self._build_snapshot(current_outstanding, bundle_units, limits.max_outstanding_requests, "outstanding")
            return QuotaCheckResult(
                allowed=False,
                reason=f"Outstanding work limit exceeded: {current_outstanding} + {bundle_units} > {limits.max_outstanding_requests}",
                quota_snapshot=snapshot,
            )

        # 4. Per-job count
        current_job_count = self.engine.automatic_drafts.count_reservations_for_job(candidate.canonical_job_id)
        if current_job_count + bundle_units > limits.max_requests_per_job:
            snapshot = self._build_snapshot(current_job_count, bundle_units, limits.max_requests_per_job, "job")
            return QuotaCheckResult(
                allowed=False,
                reason=f"Per-job limit exceeded: {current_job_count} + {bundle_units} > {limits.max_requests_per_job}",
                quota_snapshot=snapshot,
            )

        # All quota checks passed
        snapshot = {
            "run_reserved": current_run_count,
            "window_reserved": current_window_count,
            "outstanding_reserved": current_outstanding,
            "job_reserved": current_job_count,
            "bundle_units": bundle_units,
        }
        return QuotaCheckResult(allowed=True, quota_snapshot=snapshot)

    def _build_snapshot(
        self,
        current: int,
        requested: int,
        limit: int,
        limit_kind: str,
    ) -> dict[str, Any]:
        return {
            "limit_kind": limit_kind,
            "current_usage": current,
            "requested_units": requested,
            "capacity_limit": limit,
        }

