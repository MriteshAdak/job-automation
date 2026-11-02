"""Tests for RUN-01 Migration 008 application, rollback, and data preservation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import AssessmentDisposition, RunStatus
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.records import (
    AssessmentSelection,
    PostingBinding,
    RunAttempt,
    RunRequest,
)
from job_automation.storage.connection import open_connection
from job_automation.storage.engine import StorageEngine
from job_automation.storage.migrations import (
    ALL_MIGRATIONS,
    apply_migrations,
    get_current_schema_version,
)


class TestOrchestrationMigrations:
    def test_migration_008_application_and_preservation(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mig8.db"
        conn = open_connection(db_path)
        try:
            # Apply up to migration 7
            apply_migrations(conn, target_version=7)
            assert get_current_schema_version(conn) == 7

            # Insert representative pre-migration run record
            run_id = uuid.uuid4()
            summary = RunSummary(
                run_id=run_id,
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                status=RunStatus.SUCCESS,
            )
            eng7 = StorageEngine(db_path=db_path)
            eng7.runs.complete_run(summary)
            eng7.close()

            # Apply migration 8
            applied = apply_migrations(conn, target_version=8)
            assert applied == [8]
            assert get_current_schema_version(conn) == 8

            # Verify existing data preserved
            eng8 = StorageEngine(db_path=db_path)
            saved_run = eng8.runs.get_run(run_id)
            assert saved_run is not None
            assert saved_run.run_id == run_id

            # Verify new tables are functional
            attempt = RunAttempt(
                run_id=run_id,
                attempt_sequence=1,
                status="running",
            )
            eng8.pipeline_work.save_run_attempt(attempt)
            latest_att = eng8.pipeline_work.get_latest_attempt(run_id)
            assert latest_att is not None
            assert latest_att.attempt_sequence == 1

            # Save and retrieve posting binding
            can_id = uuid.uuid4()
            rev_id = uuid.uuid4()
            sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p1")
            c06 = NormalizedPosting(
                source_key=sk,
                normalizer_version="1.0",
                source_url="https://example.com/p1",
                raw_reference="raw/p1.json",
                raw_content_hash=f"sha256:{'a'*64}",
                company_name_hint="Tech Corp",
                title="Developer",
                description_clean="Clean desc",
                observed_at=datetime.now(timezone.utc),
            )
            binding = PostingBinding(
                canonical_job_id=can_id,
                revision_id=rev_id,
                normalized_content_hash=f"sha256:{'b'*64}",
                raw_reference="raw/p1.json",
                raw_content_hash=f"sha256:{'a'*64}",
                source_key=sk,
                c06_snapshot=c06,
            )
            eng8.pipeline_work.save_posting_binding(binding)
            ret_binding = eng8.pipeline_work.get_posting_binding(can_id, rev_id)
            assert ret_binding is not None
            assert ret_binding.c06_snapshot.title == "Developer"

            # Save and retrieve assessment selection
            sel = AssessmentSelection(
                canonical_job_id=can_id,
                candidate_id=uuid.uuid4(),
                purpose="assessment",
                input_fingerprint="fp123",
                assessment_id=uuid.uuid4(),
                evaluated_at=datetime.now(timezone.utc),
                generation_token="gen_1",
                is_selected_final=True,
                disposition=AssessmentDisposition.ELIGIBLE,
            )
            eng8.pipeline_work.save_assessment_selection(sel)
            ret_sel = eng8.pipeline_work.get_active_selection(can_id)
            assert ret_sel is not None
            assert ret_sel.generation_token == "gen_1"

            eng8.close()
        finally:
            conn.close()

