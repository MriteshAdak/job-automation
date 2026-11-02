"""Tests for Migration 007 (SYNC-01-S03)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from job_automation.storage.connection import open_connection
from job_automation.storage.engine import StorageEngine
from job_automation.storage.migrations import (
    apply_migrations,
    get_current_schema_version,
)


class TestSyncMigrations:
    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "sync_migration_test.db"

    def test_migration_007_applies_and_creates_tables(self, db_path: Path) -> None:
        conn = open_connection(db_path)
        applied = apply_migrations(conn, target_version=7)
        assert 7 in applied
        assert get_current_schema_version(conn) == 7

        # Verify all new tables exist in sqlite_master
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cursor.fetchall()}

        expected_tables = {
            "sync_plans",
            "sync_write_steps",
            "sync_entity_heads",
            "sync_remote_mappings",
            "sync_selection_heads",
            "candidate_snapshots",
            "candidate_backup_checkpoints",
        }
        assert expected_tables.issubset(tables)

        # Verify indexes
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        indexes = {row["name"] for row in cursor.fetchall()}
        expected_indexes = {
            "idx_sync_plans_job",
            "idx_sync_steps_plan",
            "idx_sync_steps_due",
            "idx_sync_steps_entity",
            "idx_candidate_snapshots_job",
        }
        assert expected_indexes.issubset(indexes)
        conn.close()

    def test_migration_007_preserves_existing_data(self, db_path: Path) -> None:
        conn = open_connection(db_path)
        # Apply up to migration 6
        apply_migrations(conn, target_version=6)
        assert get_current_schema_version(conn) == 6

        # Insert a canonical job
        conn.execute(
            """
            INSERT INTO canonical_jobs (
                canonical_job_id, company_name, availability, current_revision_id,
                first_seen_at, last_seen_at, job_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-uuid-1",
                "Pre-migration Corp",
                "active",
                "rev-1",
                "2026-10-29T10:00:00Z",
                "2026-10-29T10:00:00Z",
                "{}",
                "2026-10-29T10:00:00Z",
                "2026-10-29T10:00:00Z",
            ),
        )
        conn.commit()

        # Apply migration 7
        newly_applied = apply_migrations(conn, target_version=7)
        assert newly_applied == [7]
        assert get_current_schema_version(conn) == 7

        # Verify pre-existing data survives intact
        cursor = conn.execute("SELECT company_name FROM canonical_jobs WHERE canonical_job_id = 'job-uuid-1'")
        row = cursor.fetchone()
        assert row is not None
        assert row["company_name"] == "Pre-migration Corp"
        conn.close()

