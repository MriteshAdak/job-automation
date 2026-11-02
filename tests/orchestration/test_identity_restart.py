"""Tests for identity stage restart and crash recovery (RUN-01-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.service import IdentityService
from job_automation.orchestration.identity_stage import IdentityStageCoordinator
from job_automation.orchestration.records import RunAttempt, RunRequest
from job_automation.storage.engine import StorageEngine


class TestIdentityRestart:
    def test_replaying_identical_postings_preserves_canonical_identity(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ident_restart.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        att1 = RunAttempt(run_id=run_id, attempt_sequence=1, status="interrupted")
        engine.pipeline_work.save_run_attempt(att1)
        att2 = RunAttempt(run_id=run_id, attempt_sequence=2, status="running")
        engine.pipeline_work.save_run_attempt(att2)

        req = RunRequest(run_id=run_id, app_config_hash="cfg_hash")
        ident_service = IdentityService(engine)
        coord = IdentityStageCoordinator(engine, ident_service)

        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p100")
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p100",
            raw_reference="raw/p100.json",
            raw_content_hash=f"sha256:{'1'*64}",
            company_name_hint="Alpha Corp",
            title="Backend Lead",
            description_clean="Desc",
            observed_at=now,
        )

        # Attempt 1 processes posting
        res1 = coord.execute_identity(req, att1, [c06])
        job_id1 = list(res1.affected_canonical_ids)[0]
        assert res1.canonical_jobs_new == 1

        # Attempt 2 resumes and replays posting
        res2 = coord.execute_identity(req, att2, [c06])
        job_id2 = list(res2.affected_canonical_ids)[0]

        # Invariants:
        assert job_id1 == job_id2  # Canonical identity is 100% stable
        assert res2.canonical_jobs_new == 0  # Not counted as new again
        assert res2.canonical_jobs_duplicate == 1  # Counted as re-observation duplicate

        # Check total canonical jobs in DB
        all_jobs = engine.canonical_jobs.list_jobs()
        assert len(all_jobs) == 1
        assert len(all_jobs[0].revisions) == 1  # No duplicate revision created!

        engine.close()
