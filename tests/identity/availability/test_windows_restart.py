"""Native Windows separate-process restart and crash recovery verification for availability."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestWindowsRestart:
    def test_process_restart_isolation_and_availability_persistence(
        self, tmp_path: Path
    ) -> None:
        """Process manifests in a child process, exit, release locks, and inspect in parent."""
        db_path = tmp_path / "restart_avail" / "availability_restart.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        child_code = textwrap.dedent(
            f"""
            import sys, uuid
            from datetime import datetime, timezone
            from job_automation.storage.engine import StorageEngine
            from job_automation.contracts.postings import FetchManifest
            from job_automation.contracts.enums import FetchOutcome, InventorySemantics
            from job_automation.identity.availability.service import AvailabilityService

            db_path = r"{db_path}"
            with StorageEngine(db_path=db_path) as engine:
                engine.initialize_schema()
                service = AvailabilityService(engine)

                now = datetime.now(timezone.utc)
                manifest = FetchManifest(
                    run_id=uuid.uuid4(),
                    source_key="arbeitnow_de",
                    scope_id="an_de",
                    start_time=now,
                    end_time=now,
                    outcome=FetchOutcome.COMPLETE,
                    inventory_semantics=InventorySemantics.COMPLETE_BOARD,
                    page_count=1,
                    observed_posting_identities=["child_101", "child_102"],
                )
                res = service.process_manifest(manifest)
                assert res.positive_observations_count == 2
            """
        )

        proc = subprocess.run(
            [sys.executable, "-c", child_code],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Child process failed: {proc.stderr}\n{proc.stdout}"

        # Reopen in parent process and verify availability records survived cleanly
        with StorageEngine(db_path=db_path) as engine:
            service = AvailabilityService(engine)

            sk1 = SourceKey(provider="arbeitnow", board_id="de", source_posting_id="child_101")
            sk2 = SourceKey(provider="arbeitnow", board_id="de", source_posting_id="child_102")

            s1 = service.get_source_availability(sk1, "an_de")
            s2 = service.get_source_availability(sk2, "an_de")

            assert s1 is not None
            assert s1.availability == PostingAvailability.ACTIVE
            assert s2 is not None
            assert s2.availability == PostingAvailability.ACTIVE

