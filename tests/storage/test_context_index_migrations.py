"""Tests for database migration 006: context index generations, activations, builds, and pins."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from job_automation.storage.connection import open_connection
from job_automation.storage.migrations import (
    ALL_MIGRATIONS,
    apply_migrations,
    get_current_schema_version,
)


def test_migration_006_applies_cleanly(tmp_path: Path) -> None:
    db_path = tmp_path / "test_migration_006.db"
    conn = open_connection(db_path)
    try:
        # Apply up to migration 5
        applied = apply_migrations(conn, target_version=5)
        assert get_current_schema_version(conn) == 5

        # Apply migration 6
        applied_6 = apply_migrations(conn, target_version=6)
        assert applied_6 == [6]
        assert get_current_schema_version(conn) == 6

        # Verify tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'context_index_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        expected_tables = {
            "context_index_generations",
            "context_index_activations",
            "context_index_build_records",
            "context_index_pins",
        }
        assert expected_tables.issubset(tables)

        # Idempotency check: running apply_migrations again applies nothing
        reapplied = apply_migrations(conn, target_version=6)
        assert reapplied == []
    finally:
        conn.close()


def test_migration_006_preserves_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "test_migration_preserve.db"
    conn = open_connection(db_path)
    try:
        # Apply v1..v5
        apply_migrations(conn, target_version=5)

        # Insert a run record in v5 schema
        conn.execute(
            """
            INSERT INTO runs (run_id, start_time, status, created_at, updated_at)
            VALUES ('run_123', '2026-10-28T00:00:00Z', 'completed', '2026-10-28T00:00:00Z', '2026-10-28T00:00:00Z')
            """
        )
        conn.commit()

        # Apply migration 6
        apply_migrations(conn, target_version=6)

        # Verify run record intact
        cursor = conn.execute("SELECT status FROM runs WHERE run_id = 'run_123'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "completed"
    finally:
        conn.close()

