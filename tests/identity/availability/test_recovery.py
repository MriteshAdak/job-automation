"""Tests for process recovery, handle release, and database reopen (IDENTITY-02-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestRecovery:
    def test_database_close_and_reopen_preserves_availability_state(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "recovery_test.db"
        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        sk = SourceKey(provider="gh", board_id="acme", source_posting_id="101")

        # Session 1: Process manifest and persist state
        with StorageEngine(db_path=db_path) as eng1:
            eng1.migrate()
            srv1 = AvailabilityService(storage=eng1)
            manifest = FetchManifest(
                run_id=uuid.uuid4(),
                source_key="gh_acme",
                scope_id="gh_acme",
                start_time=t0,
                end_time=t0,
                outcome=FetchOutcome.COMPLETE,
                inventory_semantics=InventorySemantics.COMPLETE_BOARD,
                page_count=1,
                observed_posting_identities=["101"],
            )
            srv1.process_manifest(manifest)

        # Connection is completely closed, file locks released

        # Session 2: Open fresh StorageEngine on the existing database
        with StorageEngine(db_path=db_path) as eng2:
            srv2 = AvailabilityService(storage=eng2)
            state = srv2.get_source_availability(sk, "gh_acme")
            assert state is not None
            assert state.availability == PostingAvailability.ACTIVE
            assert state.last_seen_at == t0
            assert state.miss_count == 0

            decisions = srv2.get_decisions(source_key=sk)
            assert len(decisions) >= 1
            assert decisions[0].reason == "sighting_observed"

