"""Tests for reopening unavailable or not_seen postings via newer positive evidence (IDENTITY-02-S04)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import SourcePostingAvailability
from job_automation.identity.availability.rules import evaluate_sighting


class TestReopening:
    def test_reopen_unavailable_posting(self) -> None:
        t0 = datetime(2026, 10, 25, 8, 0, 0, tzinfo=timezone.utc)
        t_miss = datetime(2026, 10, 27, 8, 0, 0, tzinfo=timezone.utc)
        t_reopen = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)

        sk = SourceKey(provider="gh", board_id="acme", source_posting_id="101")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="gh_acme",
            canonical_job_id=uuid.uuid4(),
            availability=PostingAvailability.UNAVAILABLE,
            first_seen_at=t0,
            last_seen_at=t0,
            missing_since=t_miss,
            miss_count=3,
        )

        new_state, decision = evaluate_sighting(
            item,
            observed_at=t_reopen,
            policy_fingerprint="sha256:p1",
            manifest_id="m_reopen",
        )

        assert new_state.availability == PostingAvailability.ACTIVE
        assert new_state.last_seen_at == t_reopen
        assert new_state.missing_since is None
        assert new_state.miss_count == 0

        assert decision is not None
        assert decision.from_availability == PostingAvailability.UNAVAILABLE
        assert decision.to_availability == PostingAvailability.ACTIVE
        assert decision.reason == "reopened_by_newer_sighting"

    def test_reopen_not_seen_posting_resets_miss_streak(self) -> None:
        t0 = datetime(2026, 10, 27, 8, 0, 0, tzinfo=timezone.utc)
        t_miss = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t_fresh = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

        sk = SourceKey(provider="gh", board_id="acme", source_posting_id="101")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="gh_acme",
            availability=PostingAvailability.NOT_SEEN,
            first_seen_at=t0,
            last_seen_at=t0,
            missing_since=t_miss,
            miss_count=2,
        )

        new_state, decision = evaluate_sighting(
            item,
            observed_at=t_fresh,
            policy_fingerprint="sha256:p1",
        )

        assert new_state.availability == PostingAvailability.ACTIVE
        assert new_state.miss_count == 0
        assert new_state.missing_since is None
        assert new_state.last_seen_at == t_fresh
        assert decision is not None
        assert decision.to_availability == PostingAvailability.ACTIVE

