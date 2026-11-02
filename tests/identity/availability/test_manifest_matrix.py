"""Tests for manifest outcome and semantics matrix across service runs (IDENTITY-02-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestManifestMatrix:
    def test_empty_search_feed_causes_zero_misses(self, tmp_path) -> None:
        db_path = tmp_path / "search_empty.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)

        # Baseline posting exists
        sk = SourceKey(provider="arbeitnow", board_id="de", source_posting_id="101")
        m_base = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="arbeitnow_de",
            scope_id="an_de",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )
        service.process_manifest(m_base)

        # A subsequent search-only feed returns 0 results
        m_search = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="arbeitnow_de",
            scope_id="an_de",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.SEARCH_RESULTS,
            page_count=1,
            observed_posting_identities=[],  # Empty search feed
        )
        res = service.process_manifest(m_search)
        assert res.eligible_for_negative_inference is False
        assert res.miss_evaluations_count == 0

        # Verify posting 101 remains ACTIVE
        state = service.get_source_availability(sk, "an_de")
        assert state is not None
        assert state.availability == PostingAvailability.ACTIVE
        assert state.miss_count == 0

    def test_partial_fetch_causes_zero_misses_even_if_postings_absent(self, tmp_path) -> None:
        db_path = tmp_path / "partial_fetch.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)

        # Two postings in baseline
        sk1 = SourceKey(provider="gh", board_id="b", source_posting_id="1")
        sk2 = SourceKey(provider="gh", board_id="b", source_posting_id="2")
        m_base = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_b",
            scope_id="gh_b",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["1", "2"],
        )
        service.process_manifest(m_base)

        # Partial fetch returns only "1" (pagination stopped before getting "2")
        m_partial = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_b",
            scope_id="gh_b",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.PARTIAL,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["1"],
        )
        res = service.process_manifest(m_partial)
        assert res.eligible_for_negative_inference is False
        assert res.miss_evaluations_count == 0

        # "1" had its last_seen_at updated to t1
        s1 = service.get_source_availability(sk1, "gh_b")
        assert s1 is not None
        assert s1.last_seen_at == t1

        # "2" was NOT in the partial fetch, but MUST NOT be marked missing!
        s2 = service.get_source_availability(sk2, "gh_b")
        assert s2 is not None
        assert s2.availability == PostingAvailability.ACTIVE
        assert s2.miss_count == 0

