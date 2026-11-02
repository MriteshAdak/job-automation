"""Backup integrity verification and validation (OPS-01-S06).

Enforces:
- Manifest syntax and version compatibility.
- Presence of backup.complete atomic marker.
- File existence, size matching, and byte-for-byte SHA-256 checksum verification.
- Read-only SQLite integrity check, foreign key check, and migration checksums.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from job_automation.operations.manifest import load_manifest
from job_automation.operations.paths import validate_safe_path
from job_automation.operations.records import BackupManifest
from job_automation.storage.filestore import compute_sha256

logger = logging.getLogger(__name__)


def verify_backup(backup_dir: Path | str) -> tuple[bool, list[str]]:
    """Validate completeness, file hashes, and SQLite integrity of a backup set.

    Returns:
        (is_valid: bool, issues: list[str])
    """
    path = Path(backup_dir).resolve()
    issues: list[str] = []

    if not path.is_dir():
        return False, [f"Backup directory not found: '{path}'"]

    # 1. Completion marker check
    marker_path = path / "backup.complete"
    if not marker_path.is_file():
        issues.append(f"Incomplete backup: completion marker 'backup.complete' is missing in '{path}'")

    # 2. Manifest check
    try:
        manifest = load_manifest(path)
    except Exception as exc:
        return False, [f"Failed to load or validate manifest.json: {exc}"]

    # 3. SQLite Database Integrity
    db_file = path / "database" / "job_automation.db"
    if not db_file.is_file():
        issues.append(f"Database snapshot missing at '{db_file}'")
    else:
        try:
            # Open read-only connection
            conn = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                # PRAGMA integrity_check
                cur = conn.execute("PRAGMA integrity_check;")
                rows = [r[0] for r in cur.fetchall()]
                if rows != ["ok"]:
                    issues.append(f"SQLite PRAGMA integrity_check failed: {rows}")

                # PRAGMA foreign_key_check
                cur_fk = conn.execute("PRAGMA foreign_key_check;")
                fk_violations = cur_fk.fetchall()
                if fk_violations:
                    issues.append(f"SQLite PRAGMA foreign_key_check reported {len(fk_violations)} violations")

                # Verify schema version
                cur_v = conn.execute("SELECT MAX(version) FROM schema_migrations")
                v_row = cur_v.fetchone()
                db_ver = int(v_row[0]) if v_row and v_row[0] is not None else 0
                if db_ver != manifest.schema_version:
                    issues.append(
                        f"Database schema version ({db_ver}) does not match manifest schema_version ({manifest.schema_version})"
                    )

                # Verify migration checksums
                cur_mig = conn.execute("SELECT version, checksum FROM schema_migrations")
                for m_row in cur_mig.fetchall():
                    ver = int(m_row["version"])
                    chk = m_row["checksum"]
                    if ver in manifest.migration_checksums and manifest.migration_checksums[ver] != chk:
                        issues.append(
                            f"Migration {ver} checksum mismatch: DB has '{chk}', manifest has '{manifest.migration_checksums[ver]}'"
                        )
            finally:
                conn.close()
        except Exception as exc:
            issues.append(f"Failed to verify database file: {exc}")

    # 4. File hash and size verification
    for entry in manifest.files:
        rel = entry.root_relative_path
        try:
            file_path = validate_safe_path(rel, path)
            if not file_path.is_file():
                issues.append(f"File missing from backup: '{rel}'")
                continue

            file_bytes = file_path.read_bytes()
            if len(file_bytes) != entry.size_bytes:
                issues.append(
                    f"File size mismatch for '{rel}': expected {entry.size_bytes} bytes, got {len(file_bytes)} bytes"
                )

            actual_hash = compute_sha256(file_bytes)
            if actual_hash != entry.sha256:
                issues.append(
                    f"Content hash mismatch for '{rel}': expected '{entry.sha256}', got '{actual_hash}'"
                )
        except Exception as exc:
            issues.append(f"Error checking file '{rel}': {exc}")

    is_valid = len(issues) == 0
    return is_valid, issues

