"""Tests for SQLite database connection, PRAGMA settings, and Windows path handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_automation.storage.connection import open_connection
from job_automation.storage.engine import StorageEngine


class TestConnection:
    def test_pragmas_configured(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = open_connection(db_path)
        try:
            # Foreign keys enabled
            fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            assert fk == 1

            # WAL journal mode
            journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert journal.lower() == "wal"

            # Busy timeout >= 5000ms
            timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            assert timeout >= 5000

            # Synchronous normal
            sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
            assert sync == 1  # 1 = NORMAL
        finally:
            conn.close()

    def test_native_windows_paths_with_spaces_and_unicode(self, tmp_path: Path) -> None:
        # Path with spaces and German umlauts
        space_unicode_dir = tmp_path / "Job Automation Prüfung äöü" / "daten bank"
        db_path = space_unicode_dir / "job_test.db"

        # Directory does not exist yet
        assert not space_unicode_dir.exists()

        engine = StorageEngine(db_path=db_path)
        try:
            # Trigger connection - directory should be created
            version = engine.get_schema_version()
            assert version == 0
            assert space_unicode_dir.exists()
            assert db_path.exists()
        finally:
            engine.close()

    def test_no_directory_creation_on_import(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "should_not_exist_yet"
        db_path = target_dir / "test.db"
        # Merely instantiating StorageEngine does NOT open connection or create directory
        engine = StorageEngine(db_path=db_path)
        assert not target_dir.exists()
        assert not db_path.exists()
        engine.close()

