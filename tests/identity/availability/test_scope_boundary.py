"""Tests for scope boundary isolation, baseline enrollment, and scope changes (IDENTITY-02-S02)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestScopeBoundary:
    def test_scope_isolation_prevents_cross_scope_misses(self, tmp_path) -> None:
        db_path = tmp_path / "scope_iso.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 28, 8, 30, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)

        # Step 1: Scope Berlin observes posting 001
        m_berlin = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_berlin",
            scope_id="gh_berlin",
            start_time=t0,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["001"],
        )
        res1 = service.process_manifest(m_berlin)
        assert res1.positive_observations_count == 1

        sk = SourceKey(provider="gh", board_id="berlin", source_posting_id="001")
        state_berlin = service.get_source_availability(sk, "gh_berlin")
        assert state_berlin is not None
        assert state_berlin.availability == PostingAvailability.ACTIVE

        # Step 2: Scope Munich executes a complete fetch where 001 is NOT present (Munich board has 002)
        m_munich = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_munich",
            scope_id="gh_munich",
            start_time=t1,
            end_time=t2,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["002"],
        )
        res2 = service.process_manifest(m_munich)
        assert res2.positive_observations_count == 1
        assert res2.miss_evaluations_count == 0  # 001 is NOT in Munich baseline!

        # Verify Berlin posting 001 was NOT marked missing by Munich run!
        state_berlin_after = service.get_source_availability(sk, "gh_berlin")
        assert state_berlin_after is not None
        assert state_berlin_after.availability == PostingAvailability.ACTIVE
        assert state_berlin_after.miss_count == 0

    def test_postings_with_same_id_on_different_boards_remain_distinct(self, tmp_path) -> None:
        db_path = tmp_path / "distinct_boards.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 28, 8, 30, 0, tzinfo=timezone.utc)

        # Two different boards with identical posting id "500"
        m1 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_alpha",
            scope_id="gh_alpha",
            start_time=t0,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["500"],
        )
        m2 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_beta",
            scope_id="gh_beta",
            start_time=t0,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["500"],
        )

        service.process_manifest(m1)
        service.process_manifest(m2)

        sk_alpha = SourceKey(provider="gh", board_id="alpha", source_posting_id="500")
        sk_beta = SourceKey(provider="gh", board_id="beta", source_posting_id="500")

        state_a = service.get_source_availability(sk_alpha, "gh_alpha")
        state_b = service.get_source_availability(sk_beta, "gh_beta")

        assert state_a is not None
        assert state_b is not None
        assert state_a.source_key != state_b.source_key
        assert state_a.availability == PostingAvailability.ACTIVE
        assert state_b.availability == PostingAvailability.ACTIVE
