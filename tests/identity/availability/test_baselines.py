"""Tests for scoped baseline enrollment and chronological exclusion (IDENTITY-02-S04)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestBaselines:
    def test_posting_first_seen_after_inventory_start_excluded_from_misses(self, tmp_path) -> None:
        db_path = tmp_path / "baseline_chrono.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t_start = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)
        t_mid = datetime(2026, 10, 28, 10, 15, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 10, 28, 10, 30, 0, tzinfo=timezone.utc)

        # Pre-seed a posting observed at t_mid (e.g. from an independent single fetch or manual entry)
        sk_new = SourceKey(provider="gh", board_id="acme", source_posting_id="new_mid")
        storage.availability.save_source_availability(
            service.storage.availability._row_to_source_posting_availability(  # type: ignore
                {
                    "provider": sk_new.provider,
                    "board_id": sk_new.board_id,
                    "source_posting_id": sk_new.source_posting_id,
                    "scope_id": "gh_acme",
                    "canonical_job_id": None,
                    "availability": "active",
                    "first_seen_at": t_mid.isoformat(),
                    "last_seen_at": t_mid.isoformat(),
                    "missing_since": None,
                    "miss_count": 0,
                    "policy_fingerprint": None,
                }
            )
        )

        # Inventory started at t_start (before t_mid) and completed at t_end
        manifest = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t_start,
            end_time=t_end,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],  # Empty board
        )

        res = service.process_manifest(manifest)
        # Because sk_new was first seen AFTER t_start, it was NOT part of the expected baseline at inventory start!
        assert res.miss_evaluations_count == 0

        # Status remains active
        state = service.get_source_availability(sk_new, "gh_acme")
        assert state is not None
        assert state.availability == PostingAvailability.ACTIVE
        assert state.miss_count == 0

