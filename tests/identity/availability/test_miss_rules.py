"""Tests for repeated-miss rule transitions and streaks (IDENTITY-02-S05)."""

from __future__ import annotations

from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import SourcePostingAvailability
from job_automation.identity.availability.rules import evaluate_miss
from job_automation.identity.availability.settings import AvailabilityRuleSettings


class TestMissRules:
    def test_first_miss_transitions_active_to_not_seen(self) -> None:
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t_miss = datetime(2026, 10, 29, 8, 0, 0, tzinfo=timezone.utc)

        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.ACTIVE,
            first_seen_at=t0,
            last_seen_at=t0,
            miss_count=0,
        )

        settings = AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=172800.0)
        new_state, decision = evaluate_miss(
            current=item,
            inventory_end=t_miss,
            settings=settings,
            policy_fingerprint="sha256:fp",
        )

        assert new_state.availability == PostingAvailability.NOT_SEEN
        assert new_state.miss_count == 1
        assert new_state.missing_since == t_miss

        assert decision.from_availability == PostingAvailability.ACTIVE
        assert decision.to_availability == PostingAvailability.NOT_SEEN
        assert decision.miss_count == 1
        assert decision.reason == "absent_from_complete_inventory_streak_1"

    def test_subsequent_miss_increments_counter(self) -> None:
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t_miss1 = datetime(2026, 10, 29, 8, 0, 0, tzinfo=timezone.utc)
        t_miss2 = datetime(2026, 10, 30, 8, 0, 0, tzinfo=timezone.utc)

        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.NOT_SEEN,
            first_seen_at=t0,
            last_seen_at=t0,
            missing_since=t_miss1,
            miss_count=1,
        )

        # Settings: threshold 3, grace 48h
        settings = AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=172800.0)
        new_state, decision = evaluate_miss(
            current=item,
            inventory_end=t_miss2,
            settings=settings,
            policy_fingerprint="sha256:fp",
        )

        assert new_state.availability == PostingAvailability.NOT_SEEN
        assert new_state.miss_count == 2
        # missing_since remains anchored at t_miss1!
        assert new_state.missing_since == t_miss1
        assert decision.to_availability == PostingAvailability.NOT_SEEN

