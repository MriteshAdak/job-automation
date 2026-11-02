"""Tests for IDENTITY-02 availability contract models, boundaries, and validation (IDENTITY-02-S01)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    AvailabilityProcessResult,
    CanonicalChangeResult,
    SourceChangeResult,
    SourcePostingAvailability,
)


class TestContractBoundary:
    def test_source_posting_availability_round_trip(self) -> None:
        now = datetime.now(timezone.utc)
        cid = uuid.uuid4()
        sk = SourceKey(provider="greenhouse", board_id="acme", source_posting_id="101")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="scope-v1:test1",
            canonical_job_id=cid,
            availability=PostingAvailability.ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
            missing_since=None,
            miss_count=0,
            policy_fingerprint="sha256:abc123",
        )

        dumped = item.model_dump(mode="json")
        loaded = SourcePostingAvailability.model_validate(dumped)

        assert loaded.source_key == sk
        assert loaded.scope_id == "scope-v1:test1"
        assert loaded.canonical_job_id == cid
        assert loaded.availability == PostingAvailability.ACTIVE
        assert loaded.first_seen_at == now
        assert loaded.last_seen_at == now
        assert loaded.miss_count == 0
        assert loaded.policy_fingerprint == "sha256:abc123"

    def test_availability_models_forbid_extra_fields(self) -> None:
        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="lever", board_id="tech", source_posting_id="202")
        with pytest.raises(ValidationError):
            SourcePostingAvailability.model_validate(
                {
                    "source_key": sk.model_dump(),
                    "scope_id": "scope-v1:xyz",
                    "availability": "active",
                    "first_seen_at": now.isoformat(),
                    "last_seen_at": now.isoformat(),
                    "miss_count": 0,
                    "application_progress": "Interviewing",  # FORBIDDEN: candidate domain!
                }
            )

    def test_availability_decision_model_serialization(self) -> None:
        now = datetime.now(timezone.utc)
        did = uuid.uuid4()
        cid = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="303")
        decision = AvailabilityDecision(
            decision_id=did,
            source_key=sk,
            canonical_job_id=cid,
            scope_id="scope-v1:arbeitnow",
            manifest_id="run-1-manifest",
            run_id=uuid.uuid4(),
            from_availability=PostingAvailability.NOT_SEEN,
            to_availability=PostingAvailability.UNAVAILABLE,
            reason="consecutive_misses_3_and_grace_elapsed",
            miss_count=3,
            missing_since=now,
            event_time=now,
            policy_fingerprint="sha256:pol123",
        )

        dumped = decision.model_dump(mode="json")
        loaded = AvailabilityDecision.model_validate(dumped)
        assert loaded.decision_id == did
        assert loaded.from_availability == PostingAvailability.NOT_SEEN
        assert loaded.to_availability == PostingAvailability.UNAVAILABLE
        assert loaded.reason == "consecutive_misses_3_and_grace_elapsed"

    def test_change_results_models(self) -> None:
        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="p", board_id="b", source_posting_id="1")
        cid = uuid.uuid4()

        src_res = SourceChangeResult(
            source_key=sk,
            scope_id="s1",
            canonical_job_id=cid,
            previous_availability=PostingAvailability.ACTIVE,
            new_availability=PostingAvailability.NOT_SEEN,
            reason="miss_streak_1",
            miss_count=1,
            missing_since=now,
            transition_time=now,
        )
        assert src_res.new_availability == PostingAvailability.NOT_SEEN

        can_res = CanonicalChangeResult(
            canonical_job_id=cid,
            previous_availability=PostingAvailability.ACTIVE,
            new_availability=PostingAvailability.UNAVAILABLE,
            reason="all_sources_unavailable",
            participating_sources_count=2,
            active_sources_count=0,
            transition_time=now,
        )
        assert can_res.new_availability == PostingAvailability.UNAVAILABLE

    def test_process_result_model(self) -> None:
        rid = uuid.uuid4()
        res = AvailabilityProcessResult(
            run_id=rid,
            source_key="src1",
            scope_id="sc1",
            manifest_id="m1",
            is_complete_inventory=True,
            eligible_for_negative_inference=True,
            blocked_reason=None,
            positive_observations_count=5,
            miss_evaluations_count=2,
            is_replay=False,
        )
        assert res.positive_observations_count == 5
        assert res.is_replay is False

