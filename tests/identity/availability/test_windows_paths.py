"""Native Windows path tests with spaces and German umlauts (IDENTITY-02-S08)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


def test_windows_paths_with_spaces_and_umlauts(tmp_path: Path) -> None:
    """Verify availability storage operates cleanly on paths with spaces and German characters."""
    windows_data_dir = tmp_path / "Job Automation Verfügbarkeit Prüfung äöüß" / "Daten Größe"
    windows_data_dir.mkdir(parents=True, exist_ok=True)
    db_path = windows_data_dir / "datenbank.db"

    with StorageEngine(db_path=db_path) as storage:
        storage.migrate()
        service = AvailabilityService(storage=storage)

        now = datetime.now(timezone.utc)
        manifest = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="arbeitnow_de",
            scope_id="an_berlin_ä",
            start_time=now,
            end_time=now,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["job_äöü_1"],
        )
        result = service.process_manifest(manifest)
        assert result.positive_observations_count == 1
        assert result.is_replay is False

        sk = SourceKey(provider="arbeitnow", board_id="de", source_posting_id="job_äöü_1")
        state = service.get_source_availability(sk, "an_berlin_ä")
        assert state is not None
        assert state.availability == PostingAvailability.ACTIVE

