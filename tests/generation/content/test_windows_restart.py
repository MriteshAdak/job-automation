"""Windows subprocess restart and SQLite backup tests for GEN-03."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
import pytest

from job_automation.generation.draft_adapter import DraftGeneratorV2
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.records import StageStatus
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.storage.engine import StorageEngine


def test_windows_restart_subprocess_changed_cwd(setup_content, tmp_path: Path):
    env = setup_content(kind="cv", language="de", strategy="rag")
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure

    backup_path = tmp_path / "Wiederherstellung Größe ä.sqlite"
    target = sqlite3.connect(backup_path)
    env.engine.conn.backup(target)
    target.close()

    inv = RetentionInventoryManager(env.root).build_inventory(env.engine)
    db = next(item for item in inv.items if item.item_class.value == "database")
    assert db.is_protected
    assert any("draft_content_attempts:" in ref for ref in db.referencing_records)

    receipt_id = result.receipt.receipt_id
    restored = StorageEngine(backup_path)
    assert restored.draft_content.reopen(receipt_id) == result.receipt
    restored.close()

    # Subprocess invocation with changed CWD containing non-ASCII spaces
    cwd = tmp_path / "Anderer Ordner Prüfung ä"
    cwd.mkdir(parents=True, exist_ok=True)
    script = """import sys, uuid
from job_automation.storage.engine import StorageEngine
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.generation.draft_inputs import verify_binding
with StorageEngine(sys.argv[1]) as engine:
    receipt = engine.draft_content.reopen(uuid.UUID(sys.argv[2]))
    verify_binding(DefaultGenerationInputService(engine), receipt.request_id)
    print(receipt.content_hash)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(backup_path), str(receipt_id)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == result.receipt.content_hash


def test_restart_after_content_commit_repairs_checkpoint_without_inference(setup_content):
    env = setup_content(kind="cover_letter", language="en", strategy="json")
    env.queue()
    original = env.service.generate_content(env.request.request_id)
    assert original.failure is None, original.failure

    # Simulate restart before coordinator checkpoint
    coordinator = GenerationCoordinator(env.engine, projector=None, generator=DraftGeneratorV2(env.service))
    draft, status, error = coordinator._coordinate_draft(env.request, env.bundle)
    assert error is None
    assert status == StageStatus.COMPLETED
    assert draft == original.draft
    assert len(env.transport.recorded_calls) == 1

