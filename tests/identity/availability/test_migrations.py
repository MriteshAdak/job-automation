"""Tests for Migration 5 and schema preservation (IDENTITY-02-S03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.storage.connection import open_connection
from job_automation.storage.engine import StorageEngine
from job_automation.storage.migrations import (
    apply_migrations,
    get_current_schema_version,
)


class TestAvailabilityMigrations:
    def test_migration_005_applied_cleanly_and_preserves_existing_data(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "migration_5_test.db"
        conn = open_connection(db_path)
        try:
            # 1. Apply up to migration 4
            applied_v4 = apply_migrations(conn, target_version=4)
            assert get_current_schema_version(conn) == 4

            # 2. Seed a CanonicalJob under version 4
            now_dt = datetime.now(timezone.utc)
            job_id = uuid.uuid4()
            rev_id = uuid.uuid4()
            job = CanonicalJob(
                canonical_job_id=job_id,
                company_name="Heritage Tech GmbH",
                current_revision_id=rev_id,
                first_seen_at=now_dt,
                last_seen_at=now_dt,
                availability=PostingAvailability.ACTIVE,
            )
            eng = StorageEngine(db_path=db_path)
            eng.canonical_jobs.save_canonical_job(job)
            eng.close()

            # 3. Apply Migration 5 (availability tracking)
            applied_v5 = apply_migrations(conn, target_version=5)
            assert applied_v5 == [5]
            assert get_current_schema_version(conn) == 5

            # 4. Verify existing CanonicalJob is 100% intact
            eng_v5 = StorageEngine(db_path=db_path)
            saved_job = eng_v5.canonical_jobs.get_canonical_job(job_id)
            assert saved_job is not None
            assert saved_job.canonical_job_id == job_id
            assert saved_job.company_name == "Heritage Tech GmbH"
            assert saved_job.availability == PostingAvailability.ACTIVE

            # 5. Verify new tables are usable
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='source_posting_availability'"
            )
            assert cursor.fetchone() is not None

            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='availability_decisions'"
            )
            assert cursor.fetchone() is not None

            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='consumed_inventories'"
            )
            assert cursor.fetchone() is not None

            eng_v5.close()
        finally:
            conn.close()

