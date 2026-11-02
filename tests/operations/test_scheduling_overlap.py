"""Tests for scheduled vs manual overlap, mutual exclusion, and failure handling (AUTO-01-T06, AUTO-01-T14)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest

from job_automation.cli import main
from job_automation.orchestration.errors import LockAccessError, LockContentionError
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.operations.records import OperationsSettings
from job_automation.operations.scheduling.dispatcher import SchedulingDispatcher
from job_automation.operations.scheduling.records import OccurrenceOutcome, ScheduleKind
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def overlap_env(tmp_path: Path):
    """Set up an isolated environment with configuration and migrated storage engine."""
    data_root = tmp_path / "data_root"
    data_root.mkdir()
    config_file = tmp_path / "config.json"
    ops_config_file = tmp_path / "operations.json"

    ops_settings = OperationsSettings()
    ops_config_file.write_text(ops_settings.model_dump_json(indent=2), encoding="utf-8")

    app_config_data = {
        "app_name": "JobAutomationTest",
        "schema_version": "1.0",
        "display_timezone": "Europe/Berlin",
        "model_service_url": "http://127.0.0.1:11434",
        "operations_settings_ref": "operations.json",
    }
    config_file.write_text(json.dumps(app_config_data, indent=2), encoding="utf-8")

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    engine.migrate()
    engine.close()

    return {
        "data_root": data_root,
        "config_file": config_file,
    }


def test_manual_worker_holds_lock_scheduled_dispatch_reports_busy(overlap_env):
    """When a manual worker holds WindowsWorkerLock, scheduled dispatch exits code 3 (SKIPPED_BUSY)."""
    data_root = overlap_env["data_root"]
    config_file = overlap_env["config_file"]

    # Initialize definition with an earlier activation epoch so slot is due
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    dispatcher = SchedulingDispatcher(config_path=config_file, data_root=data_root)
    _, paths, app_config = dispatcher._get_engine_and_paths()
    definition = dispatcher.get_or_create_default_definition(engine, paths, app_config)
    definition = definition.model_copy(
        update={
            "enabled": True,
            "activation_epoch": datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc),
        }
    )
    engine.scheduling.save_definition(definition)
    engine.close()

    # 1. Manual worker acquires lock
    manual_lock = WindowsWorkerLock(data_root)

    with manual_lock.acquire(owner_kind=OwnerKind.SEARCH):
        # Verify lock file is active
        assert (data_root / ".deployment.lock").is_file()

        # 2. Run dispatcher via CLI
        rc = main([
            "ops", "schedule", "dispatch",
            "--config", str(config_file),
            "--data-root", str(data_root),
            "--as-of", "2026-10-31T10:00:00+00:00",
            "--json",
        ])

        # Must exit code 3 (LOCK_BUSY / SKIPPED_BUSY)
        assert rc == 3

    # 3. Verify launch attempt and occurrence in database
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    try:
        dep_id = definition.deployment_id
        attempts = engine.scheduling.list_launch_attempts(dep_id)
        assert len(attempts) >= 1
        latest_attempt = attempts[0]
        assert latest_attempt.child_exit_code == 3
        assert latest_attempt.outcome == "busy"

        assert latest_attempt.occurrence_id is not None
        due_occ = engine.scheduling.get_occurrence(latest_attempt.occurrence_id)
        assert due_occ is not None
        assert due_occ.outcome == OccurrenceOutcome.SKIPPED_BUSY
    finally:
        engine.close()


def test_scheduled_worker_holds_lock_manual_search_rejected(overlap_env, capsys):
    """When a scheduled worker holds the deployment lock, manual search exits with code 3."""
    data_root = overlap_env["data_root"]
    config_file = overlap_env["config_file"]

    # Simulate scheduled dispatcher holding the worker lock
    sched_lock = WindowsWorkerLock(data_root)

    with sched_lock.acquire(owner_kind=OwnerKind.SEARCH):
        # Attempt a manual search run
        rc = main([
            "run", "start",
            "--config", str(config_file),
            "--data-root", str(data_root),
            "--json",
        ])
        assert rc == 3

    out = capsys.readouterr()
    res_json = json.loads(out.out) if out.out else json.loads(out.err)
    assert res_json.get("exit_code") == 3
    assert "Pipeline lock busy" in str(res_json)


def test_maintenance_holds_lock_concurrent_search_exits_code_3(overlap_env):
    """Maintenance operations (backup) hold the lock; concurrent search is refused with code 3."""
    data_root = overlap_env["data_root"]
    config_file = overlap_env["config_file"]

    # Initialize definition with an earlier activation epoch so slot is due
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    dispatcher = SchedulingDispatcher(config_path=config_file, data_root=data_root)
    _, paths, app_config = dispatcher._get_engine_and_paths()
    definition = dispatcher.get_or_create_default_definition(engine, paths, app_config)
    definition = definition.model_copy(
        update={
            "enabled": True,
            "activation_epoch": datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc),
        }
    )
    engine.scheduling.save_definition(definition)
    engine.close()

    maint_lock = WindowsWorkerLock(data_root)

    with maint_lock.acquire(owner_kind=OwnerKind.MAINTENANCE):
        # Scheduled dispatcher should exit code 3
        rc = main([
            "ops", "schedule", "dispatch",
            "--config", str(config_file),
            "--data-root", str(data_root),
            "--as-of", "2026-10-31T10:00:00+00:00",
        ])
        assert rc == 3


def test_lock_access_error_returns_code_2(overlap_env, monkeypatch):
    """Permission or OS access error acquiring lock returns code 2 (preflight) rather than code 3 (busy)."""
    data_root = overlap_env["data_root"]
    config_file = overlap_env["config_file"]

    def mock_acquire(*args, **kwargs):
        raise LockAccessError("EACCES: Access denied opening deployment lock file")

    monkeypatch.setattr(WindowsWorkerLock, "acquire", mock_acquire)

    rc = main([
        "run", "start",
        "--config", str(config_file),
        "--data-root", str(data_root),
        "--json",
    ])
    assert rc == 2
