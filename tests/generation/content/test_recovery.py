"""Durability checks with real SQLite; inference remains scripted and offline."""
import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from job_automation.contracts.draft_content import DraftContentProposal
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.draft_adapter import DraftGeneratorV2
from job_automation.generation.draft_inputs import verify_binding
from job_automation.generation.draft_prompts import DraftRecipe
from job_automation.generation.draft_service import DraftContentService
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.generation.records import StageStatus, GenerationStage
from job_automation.models.schemas import build_default_schema_registry
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.storage.engine import StorageEngine
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.contracts.export_schemas import export_schemas


def test_commit_before_worker_checkpoint_is_reused_and_v2_validator_gate(setup_content):
    env = setup_content()
    env.queue()
    original = env.service.generate_content(env.request.request_id)
    assert original.failure is None, original.failure
    # Simulate death before GEN-01 saved any draft checkpoint.
    coordinator = GenerationCoordinator(env.engine, projector=None, generator=DraftGeneratorV2(env.service))
    draft, status, error = coordinator._coordinate_draft(env.request, env.bundle)
    assert error is None and status == StageStatus.COMPLETED and draft == original.draft
    checkpoint = env.engine.generation_work.get_checkpoint(env.request.request_id, "draft")
    assert checkpoint.checkpoint_data["draft_receipt_id"] == str(original.receipt.receipt_id)
    assert "draft_json" not in checkpoint.checkpoint_data
    draft2, status, error = coordinator._coordinate_draft(env.request, env.bundle)
    assert error is None and draft2 == draft
    seal, _ = env.inputs.get_seal(env.request.request_id)
    status, error = coordinator._coordinate_validation(env.request, draft, seal.manifest)
    assert status == StageStatus.BLOCKED and error.category.value == "missing_configuration"
    assert len(env.transport.recorded_calls) == 1


@pytest.mark.parametrize("target", ["receipt", "content", "audit", "missing"])
def test_corrupt_committed_content_never_triggers_new_inference(setup_content, target):
    env = setup_content()
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    conn = env.engine.conn
    if target == "receipt":
        conn.execute("UPDATE draft_content_attempts SET receipt_hash='corrupt'")
    elif target == "content":
        conn.execute("UPDATE draft_content_attempts SET receipt_json='{}'")
    elif target == "audit":
        conn.execute("UPDATE draft_model_audits SET audit_hash='corrupt'")
    else:
        conn.execute("UPDATE draft_content_attempts SET receipt_json=NULL")
    conn.commit()
    assert env.service.generate_content(env.request.request_id).failure is not None
    assert env.service.reopen_draft(result.receipt.receipt_id).draft is None
    assert len(env.transport.recorded_calls) == 1


def test_interrupted_attempt_is_retained_and_bounded_new_call_can_complete(setup_content):
    env = setup_content()
    start = env.engine.draft_content.start_attempt
    class SimulatedDeath(BaseException):
        pass
    def started_then_died(*args):
        start(*args)
        raise SimulatedDeath()
    env.service.repository.start_attempt = started_then_died
    with pytest.raises(SimulatedDeath):
        env.service.generate_content(env.request.request_id)
    env.service.repository.start_attempt = start
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    rows = env.engine.conn.execute("SELECT completed_at FROM draft_content_attempts").fetchall()
    assert len(rows) == 2 and sum(r[0] is None for r in rows) == 1
    assert len(env.transport.recorded_calls) == 1


def test_capacity_failure_never_returns_usable_content(setup_content):
    env = setup_content()
    def full(*args):
        error = sqlite3.OperationalError("private source sentinel")
        error.sqlite_errorcode = sqlite3.SQLITE_FULL
        raise error
    env.service.repository.finish_attempt = full
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.draft is None and result.failure.category.value == "capacity"
    assert "private source" not in result.failure.model_dump_json()
    assert env.engine.conn.execute("SELECT COUNT(*) FROM draft_content_results").fetchone()[0] == 0


def test_frozen_generation_has_no_mutable_source_reads(setup_content):
    env = setup_content(strategy="rag")
    class NoMutableReads:
        def __getattr__(self, name):
            raise AssertionError("Mutable source read: " + name)
    env.inputs.input_resolver = NoMutableReads()
    env.inputs.context_assembler = NoMutableReads()
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    # Newly configured prompt/model settings do not replace a frozen recipe.
    env.inputs.settings = env.inputs.settings.model_copy(update={"default_instruction_text_cv": "changed", "default_model_identifier": "changed"})
    assert env.service.generate_content(env.request.request_id) == result


def test_frozen_body_and_prompt_corruption_fail_before_generation(setup_content):
    env = setup_content()
    seal, _ = env.inputs.get_seal(env.request.request_id)
    corrupted = seal.model_dump(mode="json")
    corrupted["profile_snapshot"]["snapshot"]["evidence_records"][0]["skills"].append("Rust")
    env.engine.conn.execute("UPDATE generation_frozen_seals SET seal_json=?", (json.dumps(corrupted),))
    env.engine.conn.commit()
    assert env.service.generate_content(env.request.request_id).failure is not None
    assert not env.transport.recorded_calls


def test_windows_restart_changed_cwd_and_sqlite_backup(setup_content, tmp_path):
    env = setup_content(strategy="rag")
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
    # A native process starts from a different directory containing Unicode/spaces.
    cwd = tmp_path / "Anderer Ordner Prüfung ä"
    cwd.mkdir()
    script = """import sys, uuid
from job_automation.storage.engine import StorageEngine
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.generation.draft_inputs import verify_binding
with StorageEngine(sys.argv[1]) as engine:
    receipt = engine.draft_content.reopen(uuid.UUID(sys.argv[2]))
    verify_binding(DefaultGenerationInputService(engine), receipt.request_id)
    print(receipt.content_hash)
"""
    finished = subprocess.run([sys.executable, "-c", script, str(backup_path), str(receipt_id)], cwd=cwd, capture_output=True, text=True, timeout=30)
    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip() == result.receipt.content_hash


def test_schema_exports_keep_legacy_and_v2_distinct(tmp_path):
    export_schemas(tmp_path / "v1")
    legacy = json.loads((tmp_path / "v1/C14_draft_document.schema.json").read_text(encoding="utf-8"))
    v2 = json.loads((tmp_path / "v2/draft_document.schema.json").read_text(encoding="utf-8"))
    assert legacy["properties"]["schema_version"]["default"] == "1.0"
    assert v2["properties"]["schema_version"]["const"] == "2.0"
