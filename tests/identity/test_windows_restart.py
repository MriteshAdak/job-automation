"""Native Windows separate-process restart and crash recovery verification."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from job_automation.identity import IdentityService
from job_automation.storage.engine import StorageEngine


class TestWindowsRestart:
    def test_process_restart_isolation_and_merge_reversal(self, tmp_path: Path) -> None:
        """Write canonical jobs and merge in a child process, then verify and reverse in parent."""
        db_path = tmp_path / "restart_data" / "identity_restart.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        child_code = textwrap.dedent(f"""
            import sys, uuid
            from datetime import datetime, timezone
            from job_automation.storage.engine import StorageEngine
            from job_automation.contracts.postings import NormalizedPosting
            from job_automation.contracts.primitives import SourceKey
            from job_automation.identity.service import IdentityService

            db_path = r"{db_path}"
            with StorageEngine(db_path=db_path) as engine:
                engine.initialize_schema()
                service = IdentityService(engine)

                p1 = NormalizedPosting(
                    source_key=SourceKey(provider="prov_1", board_id="main", source_posting_id="101"),
                    normalizer_version="1.0-child",
                    raw_reference="raw/101.json",
                    raw_content_hash="sha256:" + "0" * 64,
                    company_name_hint="Restart Corp",
                    title="Process Engineer 1",
                    description_clean="Process automation and robotics.",
                    source_url="https://example.com/child/1",
                    observed_at=datetime.now(timezone.utc),
                )
                p2 = NormalizedPosting(
                    source_key=SourceKey(provider="prov_2", board_id="feed", source_posting_id="202"),
                    normalizer_version="1.0-child",
                    raw_reference="raw/202.json",
                    raw_content_hash="sha256:" + "0" * 64,
                    company_name_hint="Restart Corp",
                    title="Process Engineer 2",
                    description_clean="Process automation and robotics.",
                    source_url="https://example.com/child/2",
                    observed_at=datetime.now(timezone.utc),
                )

                res1 = service.resolve_and_commit(p1)
                res2 = service.resolve_and_commit(p2)

                # Merge p2 into p1
                op = service.merge_canonical_jobs(
                    surviving_id=res1.canonical_job_id,
                    merged_id=res2.canonical_job_id,
                    actor="child_worker",
                    reason="Child process initial merge",
                )
                print(f"MERGED:{{res1.canonical_job_id}}:{{res2.canonical_job_id}}:{{op.operation_id}}")
        """)

        # Execute child process
        proc = subprocess.run(
            [sys.executable, "-c", child_code],
            capture_output=True,
            text=True,
            check=True,
        )
        assert proc.returncode == 0
        output_line = [line for line in proc.stdout.splitlines() if line.startswith("MERGED:")][0]
        _, id1_str, id2_str, op_id = output_line.split(":")

        import uuid
        job_a_id = uuid.UUID(id1_str)
        job_b_id = uuid.UUID(id2_str)

        # Parent process opens database and reverses merge
        with StorageEngine(db_path=db_path) as engine:
            service = IdentityService(engine)

            # Confirm state survived child process termination
            merged_job = engine.canonical_jobs.get_canonical_job(job_a_id)
            assert merged_job is not None
            assert len(merged_job.linked_source_keys) == 2

            # Execute reversal in parent process
            reversal = service.reverse_merge(
                operation_id=op_id,
                actor="parent_process",
                reason="Reversing child process merge after restart",
            )
            assert reversal.surviving_canonical_id == job_a_id
            assert reversal.restored_canonical_id == job_b_id

            # Verify both canonical jobs are independent
            restored_a = engine.canonical_jobs.get_canonical_job(job_a_id)
            restored_b = engine.canonical_jobs.get_canonical_job(job_b_id)
            assert restored_a is not None and restored_b is not None
            assert len(restored_a.linked_source_keys) == 1
            assert len(restored_b.linked_source_keys) == 1
            assert restored_a.linked_source_keys[0].provider == "prov_1"
            assert restored_b.linked_source_keys[0].provider == "prov_2"

