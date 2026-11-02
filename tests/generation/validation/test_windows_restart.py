"""Windows subprocess restart and SQLite backup tests for GEN-04."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
import pytest

from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.storage.engine import StorageEngine


def test_windows_restart_subprocess_reopening_validation_report(setup_validation, tmp_path: Path):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None
    report_id = res.report.report_id

    # 1. Hot SQLite backup to a path with non-ASCII spaces/umlauts
    backup_path = tmp_path / "Wiederherstellung Validierung Größe ä.sqlite"
    target = sqlite3.connect(backup_path)
    env.engine.conn.backup(target)
    target.close()

    # 2. Verify retention inventory protects document_validation_attempts
    inv = RetentionInventoryManager(env.root).build_inventory(env.engine)
    db = next(item for item in inv.items if item.item_class.value == "database")
    assert db.is_protected
    assert any("document_validation_attempts:" in ref for ref in db.referencing_records)

    # 3. Subprocess execution from a changed working directory with non-ASCII spaces
    cwd = tmp_path / "Anderer Ordner Prüfung ä"
    cwd.mkdir(parents=True, exist_ok=True)

    script = """import sys, uuid
from job_automation.storage.engine import StorageEngine
with StorageEngine(sys.argv[1]) as engine:
    report = engine.document_validations.reopen(uuid.UUID(sys.argv[2]))
    print(report.report_hash)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(backup_path), str(report_id)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == res.report.report_hash

