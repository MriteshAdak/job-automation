"""Tests for observation handling, last_seen progression, and out-of-order rejection (IDENTITY-02-S04)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import SourcePostingAvailability
from job_automation.identity.availability.rules import evaluate_sighting


class TestObservations:
    def test_sighting_advances_last_seen_at(self) -> None:
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)

        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.ACTIVE,
            first_seen_at=t0,
            last_seen_at=t0,
            miss_count=0,
        )

        new_state, decision = evaluate_sighting(item, observed_at=t1, policy_fingerprint="sha256:1")
        assert new_state.last_seen_at == t1
        assert new_state.first_seen_at == t0
        assert new_state.availability == PostingAvailability.ACTIVE
        assert decision is None  # Already active with 0 misses, no transition event

    def test_out_of_order_older_sighting_rejected(self) -> None:
        t1 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)
        t_older = datetime(2026, 10, 28, 8, 30, 0, tzinfo=timezone.utc)

        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="sc",
            availability=PostingAvailability.NOT_SEEN,
            first_seen_at=t1,
            last_seen_at=t1,
            miss_count=1,
            missing_since=t1,
        )

        # An older cached page delivered with timestamp t_older < last_seen_at
        new_state, decision = evaluate_sighting(item, observed_at=t_older, policy_fingerprint="sha256:1")
        assert new_state == item
        assert new_state.last_seen_at == t1
        assert new_state.availability == PostingAvailability.NOT_SEEN
        assert new_state.miss_count == 1
        assert decision is None

