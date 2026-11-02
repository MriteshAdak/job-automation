"""Dispatcher and lifecycle recovery tests (AUTO-01-T01, T04, T07, T09, T10)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import pytest

from job_automation.operations.records import OperationsSettings
from job_automation.operations.scheduling.dispatcher import SchedulingDispatcher
from job_automation.operations.scheduling.launcher import LaunchResult
from job_automation.operations.scheduling.readiness import ReadinessProbeResult
from job_automation.operations.scheduling.records import (
    BootstrapCategory,
    OccurrenceOutcome,
    ScheduleDefinition,
    ScheduleOccurrence,
    ScheduleKind,
)
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def disp_env(tmp_path: Path):
    """Set up an isolated environment with configuration and storage engine."""
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


def test_nominal_scheduled_dispatch_success(disp_env):
    """T01: Dispatcher admits due slot, executes child, updates occurrence to SUCCEEDED and saves launch audit."""
    data_root = disp_env["data_root"]
    config_file = disp_env["config_file"]

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    dispatcher = SchedulingDispatcher(config_path=config_file, data_root=data_root)
    _, paths, app_config = dispatcher._get_engine_and_paths()

    # Create enabled definition with activation epoch in the past
    def_obj = dispatcher.get_or_create_default_definition(engine, paths, app_config)
    def_obj = def_obj.model_copy(
        update={
            "enabled": True,
            "activation_epoch": datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc),
        }
    )
    engine.scheduling.save_definition(def_obj)
    engine.close()

    mock_run_id = uuid.uuid4()
    mock_res = LaunchResult(
        exit_code=0,
        outcome="success",
        stdout=json.dumps({"run_id": str(mock_run_id), "status": "completed"}),
        stderr="",
        duration_seconds=1.2,
        pid=12345,
        run_id=mock_run_id,
        json_payload={"run_id": str(mock_run_id), "status": "completed"},
    )

    with patch.object(dispatcher.launcher, "launch", return_value=mock_res) as mock_launch:
        as_of = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
        report = dispatcher.dispatch(as_of_utc=as_of)

        assert report.exit_code == 0
        assert report.status == "success"
        assert report.occurrence_id is not None
        assert report.run_id == mock_run_id

        # Verify command arguments passed to launcher
        mock_launch.assert_called_once()
        call_args = mock_launch.call_args[0][0]
        assert "run" in call_args
        assert "start" in call_args
        assert "--trigger-kind" in call_args
        assert "scheduled" in call_args
        assert "--schedule-occurrence-id" in call_args
        assert str(report.occurrence_id) in call_args

    # Verify occurrence and launch attempt persisted in database
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    try:
        occ = engine.scheduling.get_occurrence(report.occurrence_id)
        assert occ is not None
        assert occ.outcome == OccurrenceOutcome.SUCCEEDED
        assert occ.admitted_run_id == mock_run_id
        assert occ.terminal_at is not None

        attempts = engine.scheduling.list_launch_attempts(occurrence_id=report.occurrence_id)
        assert len(attempts) == 1
        att = attempts[0]
        assert att.child_exit_code == 0
        assert att.outcome == "success"
        assert att.application_run_id == mock_run_id
    finally:
        engine.close()


def test_idle_dispatch_when_no_slots_due(disp_env):
    """T04: When no slots are due, dispatcher returns status 'idle' with code 0 without launching child."""
    data_root = disp_env["data_root"]
    config_file = disp_env["config_file"]

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    dispatcher = SchedulingDispatcher(config_path=config_file, data_root=data_root)
    _, paths, app_config = dispatcher._get_engine_and_paths()

    # Definition activation epoch set in future relative to as_of
    def_obj = dispatcher.get_or_create_default_definition(engine, paths, app_config)
    def_obj = def_obj.model_copy(
        update={
            "enabled": True,
            "activation_epoch": datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
        }
    )
    engine.scheduling.save_definition(def_obj)
    engine.close()

    with patch.object(dispatcher.launcher, "launch") as mock_launch:
        as_of = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
        report = dispatcher.dispatch(as_of_utc=as_of)

        assert report.exit_code == 0
        assert report.status == "idle"
        mock_launch.assert_not_called()


def test_resume_interrupted_run(disp_env):
    """T07: When an occurrence is IN_PROGRESS with an admitted run ID, dispatcher resumes it."""
    data_root = disp_env["data_root"]
    config_file = disp_env["config_file"]

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    dispatcher = SchedulingDispatcher(config_path=config_file, data_root=data_root)
    _, paths, app_config = dispatcher._get_engine_and_paths()

    def_obj = dispatcher.get_or_create_default_definition(engine, paths, app_config)
    def_obj = def_obj.model_copy(update={"enabled": True})
    engine.scheduling.save_definition(def_obj)

    # Seed an unfinished occurrence in IN_PROGRESS
    prev_run_id = uuid.uuid4()
    occ_id = uuid.uuid4()
    now_utc = datetime.now(timezone.utc)
    unfinished_occ = ScheduleOccurrence(
        occurrence_id=occ_id,
        deployment_id=def_obj.deployment_id,
        schedule_id=def_obj.schedule_id,
        definition_version=def_obj.version,
        work_kind=def_obj.work_kind,
        intended_slot="2026-10-31T07:00:00 Europe/Berlin",
        intended_utc_instant=now_utc - timedelta(hours=1),
        local_offset_minutes=60,
        fold=0,
        outcome=OccurrenceOutcome.IN_PROGRESS,
        admitted_run_id=prev_run_id,
        created_at=now_utc - timedelta(hours=1),
        updated_at=now_utc - timedelta(hours=1),
    )
    engine.scheduling.save_occurrence(unfinished_occ)
    engine.close()

    mock_res = LaunchResult(
        exit_code=0,
        outcome="success",
        stdout=json.dumps({"run_id": str(prev_run_id), "status": "resumed_completed"}),
        stderr="",
        duration_seconds=1.5,
        pid=9999,
        run_id=prev_run_id,
    )

    with patch.object(dispatcher.launcher, "launch", return_value=mock_res) as mock_launch:
        report = dispatcher.dispatch(as_of_utc=now_utc)

        assert report.status == "resumed"
        assert report.exit_code == 0
        assert report.run_id == prev_run_id

        # Verify it called `run resume --run-id <prev_run_id>`
        mock_launch.assert_called_once()
        args = mock_launch.call_args[0][0]
        assert "resume" in args
        assert "--run-id" in args
        assert str(prev_run_id) in args

    # Verify occurrence transitioned to SUCCEEDED
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    try:
        updated_occ = engine.scheduling.get_occurrence(occ_id)
        assert updated_occ.outcome == OccurrenceOutcome.SUCCEEDED
    finally:
        engine.close()


def test_model_readiness_failure_in_llm_mode(disp_env):
    """T09: When LLM mode is active and Ollama probe fails, dispatcher records bootstrap failure and increments retries."""
    data_root = disp_env["data_root"]
    config_file = disp_env["config_file"]

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    dispatcher = SchedulingDispatcher(config_path=config_file, data_root=data_root)
    _, paths, app_config = dispatcher._get_engine_and_paths()

    def_obj = dispatcher.get_or_create_default_definition(engine, paths, app_config)
    def_obj = def_obj.model_copy(
        update={
            "enabled": True,
            "assessment_mode": "llm",
            "activation_epoch": datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc),
        }
    )
    engine.scheduling.save_definition(def_obj)
    engine.close()

    mock_unready = ReadinessProbeResult(
        is_ready=False,
        category=BootstrapCategory.RUNTIME_OFFLINE,
        details="Connection refused connecting to 127.0.0.1:11434",
    )

    with patch("job_automation.operations.scheduling.dispatcher.probe_model_readiness", return_value=mock_unready):
        with patch.object(dispatcher.launcher, "launch") as mock_launch:
            as_of = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
            report = dispatcher.dispatch(as_of_utc=as_of)

            assert report.exit_code == 2
            assert report.status == "model_offline"
            mock_launch.assert_not_called()

    # Verify occurrence and launch attempt in DB
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    try:
        occ = engine.scheduling.get_occurrence(report.occurrence_id)
        assert occ is not None
        assert occ.outcome == OccurrenceOutcome.FAILED
        assert occ.retry_count == 1
        assert occ.next_eligible_at is not None

        attempts = engine.scheduling.list_launch_attempts(occurrence_id=report.occurrence_id)
        assert len(attempts) == 1
        assert attempts[0].bootstrap_status == BootstrapCategory.RUNTIME_OFFLINE
        assert "Connection refused" in attempts[0].readiness_message
    finally:
        engine.close()


def test_max_retries_exceeded_becomes_terminal(disp_env):
    """T10: When retry count reaches max_retries, occurrence is marked terminal."""
    data_root = disp_env["data_root"]
    config_file = disp_env["config_file"]

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    dispatcher = SchedulingDispatcher(config_path=config_file, data_root=data_root)
    _, paths, app_config = dispatcher._get_engine_and_paths()

    def_obj = dispatcher.get_or_create_default_definition(engine, paths, app_config)
    def_obj = def_obj.model_copy(
        update={
            "enabled": True,
            "max_retries": 2,
            "activation_epoch": datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc),
        }
    )
    engine.scheduling.save_definition(def_obj)

    # Seed an occurrence with retry_count = 1 already
    occ_id = uuid.uuid4()
    now_utc = datetime.now(timezone.utc)
    retrying_occ = ScheduleOccurrence(
        occurrence_id=occ_id,
        deployment_id=def_obj.deployment_id,
        schedule_id=def_obj.schedule_id,
        definition_version=def_obj.version,
        work_kind=def_obj.work_kind,
        intended_slot="2026-10-31T07:00:00 Europe/Berlin",
        intended_utc_instant=now_utc - timedelta(hours=1),
        local_offset_minutes=60,
        fold=0,
        outcome=OccurrenceOutcome.FAILED,
        retry_count=1,
        next_eligible_at=now_utc - timedelta(minutes=5),
        created_at=now_utc - timedelta(hours=1),
        updated_at=now_utc - timedelta(hours=1),
    )
    engine.scheduling.save_occurrence(retrying_occ)
    engine.close()

    mock_fail = LaunchResult(
        exit_code=1,
        outcome="failed",
        stdout="",
        stderr="Fatal error in search step",
        duration_seconds=0.5,
        pid=54321,
    )

    with patch.object(dispatcher.launcher, "launch", return_value=mock_fail):
        report = dispatcher.dispatch(as_of_utc=now_utc)
        assert report.exit_code == 1

    # Verify occurrence reached terminal state (retry_count == 2 == max_retries)
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    try:
        occ = engine.scheduling.get_occurrence(report.occurrence_id)
        assert occ is not None
        assert occ.retry_count == 2
        assert occ.terminal_at is not None
        assert occ.next_eligible_at is None
    finally:
        engine.close()
