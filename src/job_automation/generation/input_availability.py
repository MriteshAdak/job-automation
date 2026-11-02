"""Authoritative availability re-checking and gate enforcement for GEN-02."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.input_errors import job_unavailable_error
from job_automation.generation.input_records import (
    AvailabilityCheck,
    compute_sha256_digest,
)
from job_automation.identity.availability.aggregate import (
    aggregate_canonical_availability,
    aggregate_observation_timestamps,
)

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class AvailabilityRechecker:
    """Performs fresh authoritative read of canonical job and linked source availability."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def recheck_availability(
        self,
        canonical_job_id: uuid.UUID,
        allow_unavailable_job: Any,
        override_provenance: str | None = None,
    ) -> tuple[AvailabilityCheck | None, ClassifiedError | None]:
        """Recheck authoritative canonical availability against IDENTITY-02 evidence.

        Enforces:
        - Fresh local database read; does not rely on cached admission.
        - Strict boolean check on allow_unavailable_job (strings or truthy values do not grant override).
        - Multi-source aggregation: any active source keeps canonical job active.
        - Decision table:
          * unavailable + override False -> rejection with job_unavailable error.
          * unavailable + override True -> proceed with job_unavailable_overridden warning.
          * unknown -> proceed with job_availability_unknown warning.
          * not_seen -> proceed with job_not_seen warning.
          * active -> proceed cleanly without warnings.
        """
        # Strict boolean validation
        strict_override = allow_unavailable_job is True

        # 1. Fetch canonical job
        job = self.engine.canonical_jobs.get_canonical_job(canonical_job_id)
        if job is None:
            err = ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Canonical job {canonical_job_id} not found",
                details={"reason_code": "job_not_found", "canonical_job_id": str(canonical_job_id)},
            )
            return None, err

        # 2. Fetch linked source availability evidence
        source_states = self.engine.availability.list_for_canonical_job(canonical_job_id)

        now_utc = datetime.now(timezone.utc)

        # 3. Aggregate canonical availability
        if source_states:
            canonical_avail, explanation = aggregate_canonical_availability(source_states)
            earliest_seen, latest_seen = aggregate_observation_timestamps(
                source_states,
                fallback_first_seen=job.first_seen_at,
                fallback_last_seen=job.last_seen_at,
            )
        else:
            canonical_avail = job.availability
            explanation = f"canonical_record_fallback ({job.availability.value})"
            earliest_seen = job.first_seen_at
            latest_seen = job.last_seen_at

        serialized_sources: list[dict[str, Any]] = [
            {
                "provider": s.source_key.provider,
                "board_id": s.source_key.board_id,
                "source_posting_id": s.source_key.source_posting_id,
                "scope_id": s.scope_id,
                "availability": s.availability.value,
                "miss_count": s.miss_count,
                "last_seen_at": s.last_seen_at.isoformat(),
            }
            for s in source_states
        ]

        warnings: list[str] = []
        override_applied = False
        decision_outcome = "proceed"
        classified_err: ClassifiedError | None = None

        if canonical_avail == PostingAvailability.UNAVAILABLE:
            if strict_override:
                decision_outcome = "proceed_with_warning"
                warnings.append("job_unavailable_overridden")
                override_applied = True
            else:
                decision_outcome = "rejected"
                classified_err = job_unavailable_error(
                    canonical_job_id=canonical_job_id,
                    details={
                        "explanation": explanation,
                        "earliest_seen": earliest_seen.isoformat(),
                        "latest_seen": latest_seen.isoformat(),
                    },
                )
        elif canonical_avail == PostingAvailability.UNKNOWN:
            decision_outcome = "proceed_with_warning"
            warnings.append("job_availability_unknown")
        elif canonical_avail == PostingAvailability.NOT_SEEN:
            decision_outcome = "proceed_with_warning"
            warnings.append("job_not_seen")
        else:
            decision_outcome = "proceed"

        digest_payload = {
            "canonical_job_id": str(canonical_job_id),
            "checked_at": now_utc.isoformat(),
            "canonical_availability": canonical_avail.value,
            "decision_outcome": decision_outcome,
            "allow_unavailable_job": strict_override,
            "override_applied": override_applied,
            "warnings": sorted(warnings),
        }
        check_digest = compute_sha256_digest(digest_payload)

        check = AvailabilityCheck(
            canonical_job_id=canonical_job_id,
            checked_at=now_utc,
            canonical_availability=canonical_avail,
            explanation=explanation,
            source_states=serialized_sources,
            decision_outcome=decision_outcome,
            allow_unavailable_job=strict_override,
            override_applied=override_applied,
            override_provenance=override_provenance if override_applied else None,
            warnings=warnings,
            earliest_seen=earliest_seen,
            latest_seen=latest_seen,
            check_digest=check_digest,
        )

        return check, classified_err

