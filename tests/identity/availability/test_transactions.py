"""Tests for atomic transactions and rollback on partial failure in availability (IDENTITY-02-S03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestAvailabilityTransactions:
    def test_partial_fault_rolls_back_all_availability_writes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "rollback_test.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        manifest = FetchManifest(
            run_id=run_id,
            source_key="src_fail",
            scope_id="scope_fail",
            start_time=now,
            end_time=now,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101", "102"],
        )

        # Inject an error during consumption recording
        with patch.object(
            storage.availability,
            "record_consumption",
            side_effect=RuntimeError("Disk write fault injected"),
        ):
            with pytest.raises(RuntimeError, match="Disk write fault injected"):
                service.process_manifest(manifest)

        # Verify ZERO rows were committed to source_posting_availability
        sk1 = SourceKey(provider="src", board_id="fail", source_posting_id="101")
        assert service.get_source_availability(sk1, "scope_fail") is None

        # Verify ZERO decisions were committed
        cursor = storage.conn.execute("SELECT COUNT(*) FROM availability_decisions")
        assert cursor.fetchone()[0] == 0

        # Verify ZERO consumption records exist
        cursor = storage.conn.execute("SELECT COUNT(*) FROM consumed_inventories")
        assert cursor.fetchone()[0] == 0

