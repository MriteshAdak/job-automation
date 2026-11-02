"""Availability tracking service coordinating evidence, rules, storage, and aggregation (IDENTITY-02-S07).

Key invariants:
- Machine-owned availability updates NEVER alter candidate application progress, decisions, or notes.
- Disappearance inferred ONLY from repeated qualifying COMPLETE inventories with COMPLETE_BOARD semantics.
- Partial, failed, search-only, and filtered feeds NEVER close jobs.
- Canonical availability remains active if at least one linked source posting is active.
- Idempotent execution and crash-safe atomic transactions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey, UtcDatetime
from job_automation.contracts.sources import SourceConfig
from job_automation.identity.availability.aggregate import (
    aggregate_canonical_availability,
    aggregate_observation_timestamps,
)
from job_automation.identity.availability.errors import AvailabilityConflictError
from job_automation.identity.availability.evidence import (
    compute_manifest_fingerprint,
    is_manifest_eligible_for_negative_inference,
)
from job_automation.identity.availability.inspection import CanonicalAvailabilitySummary
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    AvailabilityProcessResult,
    CanonicalChangeResult,
    SourceChangeResult,
    SourcePostingAvailability,
)
from job_automation.identity.availability.rules import evaluate_miss, evaluate_sighting
from job_automation.identity.availability.settings import (
    AvailabilityPolicy,
    load_availability_policy,
)
from job_automation.storage.connection import transaction

logger = logging.getLogger(__name__)


class AvailabilityService:
    """Service managing posting availability lifecycle and canonical projections."""

    def __init__(
        self,
        storage: StorageEngine,
        policy: AvailabilityPolicy | None = None,
    ) -> None:
        self.storage = storage
        self.policy = policy or load_availability_policy()

    def process_manifest(
        self,
        manifest: FetchManifest,
        source_config: SourceConfig | None = None,
    ) -> AvailabilityProcessResult:
        """Process an authoritative C04 FetchManifest and apply sightings and miss rules."""
        manifest_hash = compute_manifest_fingerprint(manifest)

        # 1. Idempotency and replay check
        consumed = self.storage.availability.get_consumed_inventory(
            manifest.run_id, manifest.source_key, manifest.scope_id
        )
        if consumed is not None:
            # If already evaluated for negative inference, replaying is a strict no-op
            if consumed["has_evaluated_negative"] == 1:
                return AvailabilityProcessResult(
                    run_id=manifest.run_id,
                    source_key=manifest.source_key,
                    scope_id=manifest.scope_id,
                    manifest_id=str(manifest.run_id),
                    is_complete_inventory=True,
                    eligible_for_negative_inference=True,
                    blocked_reason=None,
                    positive_observations_count=consumed["positive_count"],
                    miss_evaluations_count=consumed["miss_count"],
                    source_changes=[],
                    canonical_changes=[],
                    is_replay=True,
                )

            # If outcome hasn't changed and negative inference is not supported, it's also a replay
            is_eligible, _ = is_manifest_eligible_for_negative_inference(manifest)
            if not is_eligible and consumed["outcome"] == manifest.outcome.value:
                return AvailabilityProcessResult(
                    run_id=manifest.run_id,
                    source_key=manifest.source_key,
                    scope_id=manifest.scope_id,
                    manifest_id=str(manifest.run_id),
                    is_complete_inventory=False,
                    eligible_for_negative_inference=False,
                    blocked_reason="Previously consumed non-complete inventory replay",
                    positive_observations_count=consumed["positive_count"],
                    miss_evaluations_count=consumed["miss_count"],
                    source_changes=[],
                    canonical_changes=[],
                    is_replay=True,
                )

        # 2. Resolve provider and board_id for observed postings
        provider, board_id = self._resolve_provider_board(manifest, source_config)

        # 3. Atomic execution
        source_changes: list[SourceChangeResult] = []
        canonical_changes: list[CanonicalChangeResult] = []
        affected_canonical_ids: set[uuid.UUID] = set()

        with transaction(self.storage.conn):
            # A. Process positive sightings
            for pid in manifest.observed_posting_identities:
                sk = SourceKey(provider=provider, board_id=board_id, source_posting_id=pid)
                cid = self.storage.identity.get_canonical_id_for_source_key(sk)
                existing = self.storage.availability.get_source_availability(sk, manifest.scope_id)

                if existing is None:
                    existing = SourcePostingAvailability(
                        source_key=sk,
                        scope_id=manifest.scope_id,
                        canonical_job_id=cid,
                        availability=PostingAvailability.UNKNOWN,
                        first_seen_at=manifest.start_time,
                        last_seen_at=manifest.start_time,
                        miss_count=0,
                        policy_fingerprint=self.policy.fingerprint,
                    )

                new_state, decision = evaluate_sighting(
                    current=existing,
                    observed_at=manifest.end_time,
                    policy_fingerprint=self.policy.fingerprint,
                    manifest_id=str(manifest.run_id),
                    run_id=manifest.run_id,
                )

                self.storage.availability.save_source_availability(new_state)

                if decision is not None:
                    self.storage.availability.record_decision(decision)
                    source_changes.append(
                        SourceChangeResult(
                            source_key=sk,
                            scope_id=manifest.scope_id,
                            canonical_job_id=cid,
                            previous_availability=decision.from_availability,
                            new_availability=decision.to_availability,
                            reason=decision.reason,
                            miss_count=decision.miss_count,
                            missing_since=decision.missing_since,
                            transition_time=manifest.end_time,
                        )
                    )

                if cid is not None:
                    affected_canonical_ids.add(cid)

            # B. Evaluate negative disappearance evidence
            is_eligible, blocked_reason = is_manifest_eligible_for_negative_inference(manifest)
            has_evaluated_negative = 0
            miss_evaluations_count = 0

            if is_eligible:
                effective_rules = self.policy.get_effective_rules(
                    manifest.source_key, manifest.scope_id
                )
                baseline = self.storage.availability.list_scope_baseline(manifest.scope_id)
                observed_pids = set(manifest.observed_posting_identities)

                for posting in baseline:
                    # Absent from this inventory and seen before or at inventory start
                    if posting.source_key.source_posting_id not in observed_pids:
                        if posting.first_seen_at <= manifest.start_time:
                            miss_evaluations_count += 1
                            new_state, decision = evaluate_miss(
                                current=posting,
                                inventory_end=manifest.end_time,
                                settings=effective_rules,
                                policy_fingerprint=self.policy.fingerprint,
                                manifest_id=str(manifest.run_id),
                                run_id=manifest.run_id,
                            )

                            self.storage.availability.save_source_availability(new_state)
                            self.storage.availability.record_decision(decision)

                            if decision.from_availability != decision.to_availability:
                                source_changes.append(
                                    SourceChangeResult(
                                        source_key=posting.source_key,
                                        scope_id=posting.scope_id,
                                        canonical_job_id=posting.canonical_job_id,
                                        previous_availability=decision.from_availability,
                                        new_availability=decision.to_availability,
                                        reason=decision.reason,
                                        miss_count=decision.miss_count,
                                        missing_since=decision.missing_since,
                                        transition_time=manifest.end_time,
                                    )
                                )

                            if posting.canonical_job_id is not None:
                                affected_canonical_ids.add(posting.canonical_job_id)

                has_evaluated_negative = 1

            # C. Aggregate affected canonical job availabilities
            for cid in affected_canonical_ids:
                change = self._recompute_canonical_internal(
                    cid, transition_time=manifest.end_time
                )
                if change is not None:
                    canonical_changes.append(change)

            # D. Record consumption marker
            self.storage.availability.record_consumption(
                manifest_id=str(manifest.run_id),
                run_id=manifest.run_id,
                source_key=manifest.source_key,
                scope_id=manifest.scope_id,
                outcome=manifest.outcome.value,
                inventory_semantics=manifest.inventory_semantics.value,
                manifest_hash=manifest_hash,
                has_evaluated_negative=has_evaluated_negative,
                positive_count=len(manifest.observed_posting_identities),
                miss_count=miss_evaluations_count,
                change_count=len(source_changes) + len(canonical_changes),
                processed_at=manifest.end_time,
            )

        return AvailabilityProcessResult(
            run_id=manifest.run_id,
            source_key=manifest.source_key,
            scope_id=manifest.scope_id,
            manifest_id=str(manifest.run_id),
            is_complete_inventory=(manifest.outcome.value == "complete"),
            eligible_for_negative_inference=is_eligible,
            blocked_reason=blocked_reason,
            positive_observations_count=len(manifest.observed_posting_identities),
            miss_evaluations_count=miss_evaluations_count,
            source_changes=source_changes,
            canonical_changes=canonical_changes,
            is_replay=False,
        )

    def recompute_canonical_availability(
        self, canonical_job_id: uuid.UUID
    ) -> CanonicalChangeResult | None:
        """Public method to recompute canonical availability (e.g. after merge/reversal)."""
        now_utc = datetime.now(timezone.utc)
        with transaction(self.storage.conn):
            return self._recompute_canonical_internal(canonical_job_id, transition_time=now_utc)

    def _recompute_canonical_internal(
        self, canonical_job_id: uuid.UUID, transition_time: datetime
    ) -> CanonicalChangeResult | None:
        """Internal helper to aggregate source availability for a canonical job."""
        job = self.storage.canonical_jobs.get_canonical_job(canonical_job_id)
        if job is None:
            return None

        # Fetch current linked source keys from identity repository
        linked_keys = self.storage.identity.get_source_keys_for_canonical_id(canonical_job_id)
        source_states: list[SourcePostingAvailability] = []

        for sk in linked_keys:
            records = self.storage.availability.list_for_source_key(sk)
            if records:
                # Take most recent scope record for this source key
                source_states.append(records[0])
            else:
                # Default unknown state if no availability record exists yet
                source_states.append(
                    SourcePostingAvailability(
                        source_key=sk,
                        scope_id="unknown",
                        canonical_job_id=canonical_job_id,
                        availability=PostingAvailability.UNKNOWN,
                        first_seen_at=job.first_seen_at,
                        last_seen_at=job.last_seen_at,
                    )
                )

        new_avail, reason = aggregate_canonical_availability(source_states)
        earliest_seen, latest_seen = aggregate_observation_timestamps(
            source_states, fallback_first_seen=job.first_seen_at, fallback_last_seen=job.last_seen_at
        )

        needs_update = (new_avail != job.availability) or (latest_seen > job.last_seen_at)

        if needs_update:
            self.storage.canonical_jobs.update_availability(
                canonical_job_id=canonical_job_id,
                availability=new_avail,
                last_seen_at=latest_seen,
            )
            active_count = len(
                [s for s in source_states if s.availability == PostingAvailability.ACTIVE]
            )
            return CanonicalChangeResult(
                canonical_job_id=canonical_job_id,
                previous_availability=job.availability,
                new_availability=new_avail,
                reason=reason,
                participating_sources_count=len(source_states),
                active_sources_count=active_count,
                transition_time=transition_time,
            )

        return None

    def get_source_availability(
        self, source_key: SourceKey, scope_id: str
    ) -> SourcePostingAvailability | None:
        """Fetch current availability record for a source posting in a scope."""
        return self.storage.availability.get_source_availability(source_key, scope_id)

    def get_canonical_availability_summary(
        self, canonical_job_id: uuid.UUID
    ) -> CanonicalAvailabilitySummary | None:
        """Produce an inspectable summary of canonical availability and linked sources."""
        job = self.storage.canonical_jobs.get_canonical_job(canonical_job_id)
        if job is None:
            return None

        linked_keys = self.storage.identity.get_source_keys_for_canonical_id(canonical_job_id)
        source_states: list[SourcePostingAvailability] = []
        for sk in linked_keys:
            records = self.storage.availability.list_for_source_key(sk)
            if records:
                source_states.append(records[0])

        _, explanation = aggregate_canonical_availability(source_states)
        decisions = self.storage.availability.get_decisions_for_canonical_job(
            canonical_job_id, limit=20
        )
        active_count = len(
            [s for s in source_states if s.availability == PostingAvailability.ACTIVE]
        )

        return CanonicalAvailabilitySummary(
            canonical_job_id=canonical_job_id,
            company_name=job.company_name,
            canonical_availability=job.availability,
            first_seen_at=job.first_seen_at,
            last_seen_at=job.last_seen_at,
            explanation=explanation,
            linked_sources_count=len(linked_keys),
            active_sources_count=active_count,
            source_states=source_states,
            recent_decisions=decisions,
        )

    def get_decisions(
        self,
        source_key: SourceKey | None = None,
        canonical_job_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AvailabilityDecision]:
        """Query availability decisions with optional filters."""
        if source_key is not None:
            return self.storage.availability.get_decisions_for_source(source_key, limit=limit)
        if canonical_job_id is not None:
            return self.storage.availability.get_decisions_for_canonical_job(
                canonical_job_id, limit=limit
            )
        return []

    def _resolve_provider_board(
        self, manifest: FetchManifest, source_config: SourceConfig | None
    ) -> tuple[str, str]:
        """Resolve provider and board_id for postings in this manifest."""
        if source_config is not None:
            return (source_config.provider, source_config.board_id)

        # 1. Match from source_identities where source_key matches provider_board
        cursor = self.storage.conn.execute(
            """
            SELECT provider, board_id FROM source_identities
            WHERE provider || '_' || board_id = ?
            LIMIT 1
            """,
            (manifest.source_key,),
        )
        row = cursor.fetchone()
        if row:
            return (row["provider"], row["board_id"])

        # 2. Match from source_identities by scope_id
        cursor = self.storage.conn.execute(
            """
            SELECT provider, board_id FROM source_identities
            WHERE provider || '_' || board_id = ?
            LIMIT 1
            """,
            (manifest.scope_id,),
        )
        row = cursor.fetchone()
        if row:
            return (row["provider"], row["board_id"])

        # 3. Match from source_identities by provider exact
        cursor = self.storage.conn.execute(
            """
            SELECT provider, board_id FROM source_identities
            WHERE provider = ?
            LIMIT 1
            """,
            (manifest.source_key,),
        )
        row = cursor.fetchone()
        if row:
            return (row["provider"], row["board_id"])

        # 4. Fallback parsing from source_key
        if "_" in manifest.source_key:
            parts = manifest.source_key.split("_", 1)
            return (parts[0], parts[1])

        # 5. Fallback parsing from scope_id
        if "_" in manifest.scope_id and not manifest.scope_id.startswith("scope-v1:"):
            parts = manifest.scope_id.split("_", 1)
            return (parts[0], parts[1])

        return (manifest.source_key, "default")
