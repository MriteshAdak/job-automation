"""CLI tests for ops schedule subcommands (AUTO-01)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.cli import main
from job_automation.operations.records import OperationsSettings
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def sched_env(tmp_path: Path):
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


def test_cli_schedule_status(sched_env, capsys):
    """Test ops schedule status in text and json formats."""
    # 1. Human text output
    rc = main([
        "ops", "schedule", "status",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Scheduling Status Report" in captured.out
    assert "Schedule Active:      NO (Disabled)" in captured.out
    assert "Europe/Berlin" in captured.out

    # 2. JSON output
    rc_json = main([
        "ops", "schedule", "status",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--json",
    ])
    assert rc_json == 0
    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert data["timezone"] == "Europe/Berlin"
    assert data["enabled"] is False
    assert data["work_kind"] == "search"
    assert "model_status" in data


def test_cli_schedule_enable_and_disable(sched_env, capsys):
    """Test ops schedule enable and disable commands."""
    # Enable
    rc = main([
        "ops", "schedule", "enable",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--json",
    ])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "ok"
    assert data["enabled"] is True

    # Check status reflects enabled
    rc_status = main([
        "ops", "schedule", "status",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--json",
    ])
    assert rc_status == 0
    status_data = json.loads(capsys.readouterr().out)
    assert status_data["enabled"] is True

    # Disable
    rc_dis = main([
        "ops", "schedule", "disable",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
    ])
    assert rc_dis == 0
    assert "is now DISABLED" in capsys.readouterr().out


def test_cli_schedule_evaluate(sched_env, capsys):
    """Test dry-run evaluation preview of schedule slots."""
    rc = main([
        "ops", "schedule", "evaluate",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--at-time", "2026-10-31T08:00:00+00:00",
        "--json",
    ])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "deployment_id" in data
    assert data["as_of_utc"] == "2026-10-31T08:00:00+00:00"


def test_cli_schedule_dispatch_disabled(sched_env, capsys):
    """Test dispatch when schedule is disabled (should exit 0 without running)."""
    rc = main([
        "ops", "schedule", "dispatch",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--json",
    ])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "disabled"
    assert data["exit_code"] == 0


def test_cli_schedule_manifest(sched_env, capsys):
    """Test manifest generation producing non-secret environment identity and paths."""
    rc = main([
        "ops", "schedule", "manifest",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--json",
    ])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "account_name" in data
    assert "logon_type" in data
    assert data["logon_type"] == "Password"
    assert data["is_batch_logon_verified"] is False
    assert "acl_matrix" in data
    assert str(sched_env["data_root"]) in data["acl_matrix"]


def test_cli_schedule_export_tasks(sched_env, tmp_path, capsys):
    """Test exporting reviewable task XML definitions to output directory."""
    task_out = tmp_path / "exported_tasks"
    rc = main([
        "ops", "schedule", "export-tasks",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--output-dir", str(task_out),
        "--json",
    ])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert Path(data["dispatcher_xml"]).is_file()
    assert Path(data["model_supervisor_xml"]).is_file()


def test_cli_schedule_invalid_datetime(sched_env, capsys):
    """Test error handling when invalid datetime is provided to evaluate."""
    rc = main([
        "ops", "schedule", "evaluate",
        "--config", str(sched_env["config_file"]),
        "--data-root", str(sched_env["data_root"]),
        "--at-time", "not-a-datetime",
        "--json",
    ])
    assert rc == 2
    err_data = json.loads(capsys.readouterr().err)
    assert err_data["code"] == "SCHEDULE_EVALUATE_FAILED"

