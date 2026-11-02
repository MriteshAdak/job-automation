"""Tests for grace period conjunction, zero grace, and threshold boundary (IDENTITY-02-S05)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import SourcePostingAvailability
from job_automation.identity.availability.rules import evaluate_miss
from job_automation.identity.availability.settings import AvailabilityRuleSettings


class TestGrace:
    def test_threshold_met_without_grace_stays_not_seen(self) -> None:
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        # Miss 1 at 08:00
        # Miss 2 at 08:20
        # Miss 3 at 08:40 (3 misses in 40 minutes, but grace is 48 hours!)
        t_miss1 = t0
        t_miss3 = t0 + timedelta(minutes=40)

        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.NOT_SEEN,
            first_seen_at=t0 - timedelta(days=5),
            last_seen_at=t0 - timedelta(days=5),
            missing_since=t_miss1,
            miss_count=2,
        )

        settings = AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=172800.0)
        new_state, decision = evaluate_miss(
            current=item,
            inventory_end=t_miss3,
            settings=settings,
            policy_fingerprint="sha256:fp",
        )

        # Threshold 3 is met, but grace (40 mins < 48 hours) is NOT met!
        assert new_state.miss_count == 3
        assert new_state.availability == PostingAvailability.NOT_SEEN
        assert "awaiting" in decision.reason

    def test_grace_elapsed_without_threshold_stays_not_seen(self) -> None:
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        # First miss on 28 October
        # Second miss on 31 October (3 days later, grace of 48h has elapsed, but only 2 misses)
        t_miss1 = t0
        t_miss2 = t0 + timedelta(days=3)

        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.NOT_SEEN,
            first_seen_at=t0 - timedelta(days=5),
            last_seen_at=t0 - timedelta(days=5),
            missing_since=t_miss1,
            miss_count=1,
        )

        settings = AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=172800.0)
        new_state, decision = evaluate_miss(
            current=item,
            inventory_end=t_miss2,
            settings=settings,
            policy_fingerprint="sha256:fp",
        )

        # Grace is elapsed, but miss_count = 2 < 3!
        assert new_state.miss_count == 2
        assert new_state.availability == PostingAvailability.NOT_SEEN
        assert "awaiting" in decision.reason

    def test_both_threshold_and_grace_met_transitions_to_unavailable(self) -> None:
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        # Miss 1 on 28 October 08:00
        # Miss 3 on 30 October 09:00 (50 hours later >= 48 hours AND 3rd miss)
        t_miss1 = t0
        t_miss3 = t0 + timedelta(hours=50)

        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.NOT_SEEN,
            first_seen_at=t0 - timedelta(days=5),
            last_seen_at=t0 - timedelta(days=5),
            missing_since=t_miss1,
            miss_count=2,
        )

        settings = AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=172800.0)
        new_state, decision = evaluate_miss(
            current=item,
            inventory_end=t_miss3,
            settings=settings,
            policy_fingerprint="sha256:fp",
        )

        assert new_state.miss_count == 3
        assert new_state.availability == PostingAvailability.UNAVAILABLE
        assert decision.from_availability == PostingAvailability.NOT_SEEN
        assert decision.to_availability == PostingAvailability.UNAVAILABLE
        assert "grace" in decision.reason

    def test_zero_grace_still_requires_threshold(self) -> None:
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.ACTIVE,
            first_seen_at=t0,
            last_seen_at=t0,
            miss_count=0,
        )

        # Zero grace period
        settings = AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=0.0)

        # Miss 1 -> NOT_SEEN (threshold 3 not met)
        state1, dec1 = evaluate_miss(item, t0 + timedelta(hours=1), settings, "sha256:fp")
        assert state1.availability == PostingAvailability.NOT_SEEN
        assert state1.miss_count == 1

        # Miss 2 -> NOT_SEEN (threshold 3 not met)
        state2, dec2 = evaluate_miss(state1, t0 + timedelta(hours=2), settings, "sha256:fp")
        assert state2.availability == PostingAvailability.NOT_SEEN
        assert state2.miss_count == 2

        # Miss 3 -> UNAVAILABLE (threshold 3 met, grace 0 met)
        state3, dec3 = evaluate_miss(state2, t0 + timedelta(hours=3), settings, "sha256:fp")
        assert state3.availability == PostingAvailability.UNAVAILABLE
        assert state3.miss_count == 3

