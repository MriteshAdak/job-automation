"""Tests for identity stage, revision tracking, and posting bindings (RUN-01-S05)."""

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


class TestIdentityBindings:
    def test_new_and_duplicate_and_updated_revisions(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ident.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        attempt = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(attempt)

        req = RunRequest(run_id=run_id, app_config_hash="cfg_hash")
        ident_service = IdentityService(engine)
        coord = IdentityStageCoordinator(engine, ident_service)

        now = datetime.now(timezone.utc)
        sk1 = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p1")

        # 1. First observation -> creates new canonical job
        c06_1 = NormalizedPosting(
            source_key=sk1,
            normalizer_version="1.0",
            source_url="https://example.com/p1",
            raw_reference="raw/p1.json",
            raw_content_hash=f"sha256:{'1'*64}",
            company_name_hint="Acme Corp",
            title="Senior Engineer",
            description_clean="Clean desc v1",
            observed_at=now,
        )

        res1 = coord.execute_identity(req, attempt, [c06_1])
        assert res1.canonical_jobs_new == 1
        assert res1.canonical_jobs_updated == 0
        assert res1.canonical_jobs_duplicate == 0
        assert len(res1.bindings) == 1
        job_id = res1.bindings[0].canonical_job_id

        # 2. Re-observing exact same posting content -> counts as duplicate observation
        res2 = coord.execute_identity(req, attempt, [c06_1])
        assert res2.canonical_jobs_new == 0
        assert res2.canonical_jobs_updated == 0
        assert res2.canonical_jobs_duplicate == 1
        assert res2.bindings[0].canonical_job_id == job_id

        # 3. Material edit -> same canonical job, new revision
        c06_edited = NormalizedPosting(
            source_key=sk1,
            normalizer_version="1.0",
            source_url="https://example.com/p1",
            raw_reference="raw/p1_v2.json",
            raw_content_hash=f"sha256:{'2'*64}",
            company_name_hint="Acme Corp",
            title="Staff Engineer",  # Material edit
            description_clean="Clean desc v2",
            observed_at=now,
        )
        res3 = coord.execute_identity(req, attempt, [c06_edited])
        assert res3.canonical_jobs_new == 0
        assert res3.canonical_jobs_updated == 1
        assert res3.canonical_jobs_duplicate == 0
        assert res3.bindings[0].canonical_job_id == job_id
        assert res3.bindings[0].revision_id != res1.bindings[0].revision_id

        # Verify bindings stored in database
        bindings = engine.pipeline_work.list_posting_bindings_for_job(job_id)
        assert len(bindings) == 2  # Two distinct revisions

        engine.close()

