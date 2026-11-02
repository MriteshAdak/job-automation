"""Tests for AvailabilityRepository and SQLite persistence (IDENTITY-02-S03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    SourcePostingAvailability,
)
from job_automation.storage.engine import StorageEngine


class TestAvailabilityRepository:
    def test_save_and_retrieve_source_posting_availability(self, tmp_path) -> None:
        db_path = tmp_path / "repo_test.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()

        now = datetime.now(timezone.utc)
        cid = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="101")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="scope-1",
            canonical_job_id=cid,
            availability=PostingAvailability.ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
            miss_count=0,
            policy_fingerprint="sha256:test",
        )

        storage.availability.save_source_availability(item)

        loaded = storage.availability.get_source_availability(sk, "scope-1")
        assert loaded is not None
        assert loaded.source_key == sk
        assert loaded.scope_id == "scope-1"
        assert loaded.canonical_job_id == cid
        assert loaded.availability == PostingAvailability.ACTIVE
        assert loaded.miss_count == 0

        # Update miss count and missing_since
        updated = loaded.model_copy(
            update={
                "availability": PostingAvailability.NOT_SEEN,
                "miss_count": 1,
                "missing_since": now,
            }
        )
        storage.availability.save_source_availability(updated)

        reloaded = storage.availability.get_source_availability(sk, "scope-1")
        assert reloaded is not None
        assert reloaded.availability == PostingAvailability.NOT_SEEN
        assert reloaded.miss_count == 1
        assert reloaded.missing_since == now

    def test_list_scope_baseline_and_canonical_job(self, tmp_path) -> None:
        db_path = tmp_path / "baseline_test.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()

        now = datetime.now(timezone.utc)
        cid = uuid.uuid4()
        sk1 = SourceKey(provider="gh", board_id="acme", source_posting_id="1")
        sk2 = SourceKey(provider="gh", board_id="acme", source_posting_id="2")

        item1 = SourcePostingAvailability(
            source_key=sk1,
            scope_id="gh_acme",
            canonical_job_id=cid,
            availability=PostingAvailability.ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
        )
        item2 = SourcePostingAvailability(
            source_key=sk2,
            scope_id="gh_acme",
            canonical_job_id=None,
            availability=PostingAvailability.ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
        )

        storage.availability.save_source_availability(item1)
        storage.availability.save_source_availability(item2)

        baseline = storage.availability.list_scope_baseline("gh_acme")
        assert len(baseline) == 2

        mapped = storage.availability.list_for_canonical_job(cid)
        assert len(mapped) == 1
        assert mapped[0].source_key == sk1

    def test_record_and_retrieve_decisions(self, tmp_path) -> None:
        db_path = tmp_path / "decisions_test.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()

        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="gh", board_id="acme", source_posting_id="99")
        cid = uuid.uuid4()
        decision = AvailabilityDecision(
            source_key=sk,
            canonical_job_id=cid,
            scope_id="gh_acme",
            manifest_id="m-1",
            from_availability=PostingAvailability.ACTIVE,
            to_availability=PostingAvailability.NOT_SEEN,
            reason="miss_streak_1",
            miss_count=1,
            missing_since=now,
            event_time=now,
            policy_fingerprint="sha256:pol",
        )

        storage.availability.record_decision(decision)

        decisions_by_source = storage.availability.get_decisions_for_source(sk)
        assert len(decisions_by_source) == 1
        assert decisions_by_source[0].reason == "miss_streak_1"

        decisions_by_canonical = storage.availability.get_decisions_for_canonical_job(cid)
        assert len(decisions_by_canonical) == 1
        assert decisions_by_canonical[0].decision_id == decision.decision_id

    def test_record_consumption_and_idempotency_lookup(self, tmp_path) -> None:
        db_path = tmp_path / "consume_test.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()

        now = datetime.now(timezone.utc)
        rid = uuid.uuid4()
        storage.availability.record_consumption(
            manifest_id="m-100",
            run_id=rid,
            source_key="src_1",
            scope_id="scope_1",
            outcome="complete",
            inventory_semantics="complete_board",
            manifest_hash="sha256:hash1",
            has_evaluated_negative=1,
            positive_count=10,
            miss_count=2,
            change_count=3,
            processed_at=now,
        )

        record = storage.availability.get_consumed_inventory(rid, "src_1", "scope_1")
        assert record is not None
        assert record["manifest_id"] == "m-100"
        assert record["has_evaluated_negative"] == 1
        assert record["positive_count"] == 10
        assert record["miss_count"] == 2

