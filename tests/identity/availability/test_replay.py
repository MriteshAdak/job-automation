"""Tests for idempotent manifest replay and partial-to-complete finalization (IDENTITY-02-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestReplay:
    def test_complete_manifest_replay_is_idempotent(self, tmp_path) -> None:
        db_path = tmp_path / "replay_test.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        run_id = uuid.uuid4()
        manifest = FetchManifest(
            run_id=run_id,
            source_key="an_src",
            scope_id="an_de",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )

        # First execution
        res1 = service.process_manifest(manifest)
        assert res1.is_replay is False
        assert res1.positive_observations_count == 1

        cursor = storage.conn.execute("SELECT COUNT(*) FROM availability_decisions")
        decisions_count1 = cursor.fetchone()[0]

        # Second execution with exact same manifest (Replay)
        res2 = service.process_manifest(manifest)
        assert res2.is_replay is True
        assert res2.source_changes == []
        assert res2.canonical_changes == []

        # Decision count in database MUST NOT increase!
        cursor = storage.conn.execute("SELECT COUNT(*) FROM availability_decisions")
        decisions_count2 = cursor.fetchone()[0]
        assert decisions_count1 == decisions_count2

    def test_partial_to_complete_manifest_progression(self, tmp_path) -> None:
        db_path = tmp_path / "partial_to_complete.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 27, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)

        # Baseline: posting 200 observed yesterday
        m_base = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="an_src",
            scope_id="an_de",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["200"],
        )
        service.process_manifest(m_base)

        run_id = uuid.uuid4()
        # Step 1: Run encounters page limit, creates PARTIAL manifest observing "101" (missing "200")
        m_partial = FetchManifest(
            run_id=run_id,
            source_key="an_src",
            scope_id="an_de",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.PARTIAL,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )
        res_part = service.process_manifest(m_partial)
        assert res_part.eligible_for_negative_inference is False
        assert res_part.miss_evaluations_count == 0

        # Step 2: Ingestion resumes and finalizes to COMPLETE (observing only "101")
        m_complete = FetchManifest(
            run_id=run_id,
            source_key="an_src",
            scope_id="an_de",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=2,
            observed_posting_identities=["101"],
        )
        res_comp = service.process_manifest(m_complete)
        assert res_comp.eligible_for_negative_inference is True
        assert res_comp.miss_evaluations_count == 1  # Evaluates "200"

        # Verify "200" has miss_count == 1
        sk200 = SourceKey(provider="an", board_id="src", source_posting_id="200")
        s200 = service.get_source_availability(sk200, "an_de")
        assert s200 is not None
        assert s200.availability == PostingAvailability.NOT_SEEN
        assert s200.miss_count == 1

        # Step 3: Replaying the complete manifest again is a strict replay
        res_comp_replay = service.process_manifest(m_complete)
        assert res_comp_replay.is_replay is True

        # "200" must NOT have miss_count incremented to 2!
        s200_after = service.get_source_availability(sk200, "an_de")
        assert s200_after is not None
        assert s200_after.miss_count == 1

