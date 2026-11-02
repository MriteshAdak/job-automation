"""Tests for schema migrations, rollback on failure, and data preservation across upgrades."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability, RunStatus
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.runs import RunSummary
from job_automation.storage.connection import open_connection
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import MigrationError
from job_automation.storage.migrations import (
    ALL_MIGRATIONS,
    Migration,
    apply_migrations,
    get_applied_migrations,
    get_current_schema_version,
)


class TestMigrations:
    def test_sequential_migration_and_data_preservation(self, tmp_path: Path) -> None:
        db_path = tmp_path / "migrate_test.db"
        conn = open_connection(db_path)
        try:
            # 1. Apply Migration 1 only
            applied_v1 = apply_migrations(conn, target_version=1)
            assert applied_v1 == [1]
            assert get_current_schema_version(conn) == 1

            # 2. Insert representative data under version 1
            now_dt = datetime.now(timezone.utc)
            run_id = uuid.uuid4()
            job_id = uuid.uuid4()

            # Insert run
            summary = RunSummary(
                run_id=run_id,
                start_time=now_dt,
                end_time=now_dt,
                status=RunStatus.SUCCESS,
                source_postings_count=10,
                canonical_jobs_new=3,
                canonical_jobs_duplicate=1,
            )
            eng1 = StorageEngine(db_path=db_path)
            eng1.runs.complete_run(summary)

            # Insert raw posting
            sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="101")
            ref, hash_val = eng1.filestore.save_raw_payload(
                provider=sk.provider,
                board_id=sk.board_id,
                source_posting_id=sk.source_posting_id,
                payload='{"title": "Dev"}',
            )
            raw = RawPosting(
                raw_payload_ref=ref,
                raw_content_hash=hash_val,
                source_key=sk,
                fetch_time=now_dt,
                raw_payload='{"title": "Dev"}',
            )
            eng1.raw_postings.save_raw_posting(raw)

            # Insert canonical job
            job = CanonicalJob(
                canonical_job_id=job_id,
                company_name="Preserved Corp",
                current_revision_id=uuid.uuid4(),
                first_seen_at=now_dt,
                last_seen_at=now_dt,
                availability=PostingAvailability.ACTIVE,
            )
            eng1.canonical_jobs.save_canonical_job(job)
            eng1.close()

            # 3. Apply Migration 2 (adds pipeline_checkpoints and columns)
            applied_v2 = apply_migrations(conn, target_version=2)
            assert applied_v2 == [2]
            assert get_current_schema_version(conn) == 2

            # 4. Verify ALL existing data is 100% preserved
            eng2 = StorageEngine(db_path=db_path)
            saved_run = eng2.runs.get_run(run_id)
            assert saved_run is not None
            assert saved_run.run_id == run_id
            assert saved_run.canonical_jobs_new == 3
            assert saved_run.status == RunStatus.SUCCESS

            saved_raw = eng2.raw_postings.get_raw_posting(sk)
            assert saved_raw is not None
            assert saved_raw.raw_content_hash == raw.raw_content_hash

            saved_job = eng2.canonical_jobs.get_canonical_job(job_id)
            assert saved_job is not None
            assert saved_job.company_name == "Preserved Corp"
            assert saved_job.availability == PostingAvailability.ACTIVE

            # 5. Verify new v2 capabilities work with preserved data
            eng2.runs.save_checkpoint(
                run_id=run_id,
                stage_name="fetch",
                checkpoint_key="page_cursor",
                data={"cursor": "p_2", "items_processed": 50},
            )
            chk = eng2.runs.get_checkpoint(run_id, "fetch", "page_cursor")
            assert chk is not None
            assert chk["cursor"] == "p_2"

            eng2.close()

            # 6. Apply Migration 3 (adds profile storage)
            applied_v3 = apply_migrations(conn, target_version=3)
            assert applied_v3 == [3]
            assert get_current_schema_version(conn) == 3

            # 7. Verify all data from v1 and v2 still intact
            eng3 = StorageEngine(db_path=db_path)
            assert eng3.runs.get_run(run_id) is not None
            assert eng3.raw_postings.get_raw_posting(sk) is not None
            assert eng3.canonical_jobs.get_canonical_job(job_id) is not None
            assert eng3.runs.get_checkpoint(run_id, "fetch", "page_cursor") is not None
            eng3.close()
        finally:
            conn.close()

    def test_idempotent_migration(self, tmp_path: Path) -> None:
        db_path = tmp_path / "idempotent.db"
        conn = open_connection(db_path)
        try:
            # First run applies migrations
            first_run = apply_migrations(conn)
            assert len(first_run) > 0

            # Second run applies nothing
            second_run = apply_migrations(conn)
            assert second_run == []
            assert get_current_schema_version(conn) == len(ALL_MIGRATIONS)
        finally:
            conn.close()

    def test_migration_rollback_on_failure(self, tmp_path: Path) -> None:
        db_path = tmp_path / "failed_migration.db"
        conn = open_connection(db_path)
        try:
            # Apply migration 1
            apply_migrations(conn, target_version=1)
            assert get_current_schema_version(conn) == 1

            # Prepare a faulty migration 2 with bad SQL
            faulty_migration = Migration(
                version=2,
                name="002_faulty",
                sql="CREATE TABLE valid_table (id INT); SYNTAX ERROR THIS IS INVALID SQL;",
            )
            migrations_suite = (ALL_MIGRATIONS[0], faulty_migration)

            with pytest.raises(MigrationError) as exc_info:
                apply_migrations(conn, target_version=2, migrations=migrations_suite)

            assert "Failed to apply migration 2" in str(exc_info.value)

            # Schema version must remain at 1
            assert get_current_schema_version(conn) == 1

            # The partially created table from faulty migration must NOT exist (rolled back)
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='valid_table'"
            )
            assert cur.fetchone() is None
        finally:
            conn.close()

    def test_checksum_mismatch_detection(self, tmp_path: Path) -> None:
        db_path = tmp_path / "checksum.db"
        conn = open_connection(db_path)
        try:
            apply_migrations(conn, target_version=1)

            # Tampered migration 1 with different SQL
            tampered = (
                Migration(version=1, name="001_initial", sql="-- altered SQL content"),
            )

            with pytest.raises(MigrationError, match="checksum mismatch"):
                apply_migrations(conn, target_version=1, migrations=tampered)
        finally:
            conn.close()
