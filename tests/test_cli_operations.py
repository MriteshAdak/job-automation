"""Integration and unit tests for operations CLI commands (OPS-01-S08)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.cli import main
from job_automation.configuration import AppConfig, ResolvedPaths
from job_automation.contracts.artifacts import Artifact, DocumentApproval
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.enums import DocumentType, GenerationProcessing
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.operations.records import OperationsSettings
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def ops_env(tmp_path: Path):
    """Set up an isolated environment with configuration, storage engine, and seed data."""
    data_root = tmp_path / "data_root"
    data_root.mkdir()
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()

    config_file = tmp_path / "config.json"
    ops_config_file = tmp_path / "operations.json"

    ops_settings = OperationsSettings()
    ops_config_file.write_text(ops_settings.model_dump_json(indent=2), encoding="utf-8")

    app_config_data = {
        "app_name": "JobAutomationTest",
        "schema_version": "1.0",
        "display_timezone": "UTC",
        "model_service_url": "http://localhost:8000",
        "operations_settings_ref": "operations.json",
    }
    config_file.write_text(json.dumps(app_config_data, indent=2), encoding="utf-8")

    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
    engine.migrate()

    # Seed data
    now_dt = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    req_id = uuid.uuid4()
    art_id = uuid.uuid4()

    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    engine.generation_requests.create_request(
        GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="cv_standard",
            created_at=now_dt,
            state=GenerationProcessing.READY_FOR_REVIEW,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1",
                profile_version="1",
                policy_version="1",
                template_version="1",
            ),
        )
    )

    art_path, art_hash, art_size = engine.filestore.save_artifact_file(
        request_id=req_id,
        filename="Resume.pdf",
        content=b"%PDF-1.4 test payload",
    )
    engine.artifacts.save_artifact(
        Artifact(
            artifact_id=art_id,
            request_id=req_id,
            format="pdf",
            local_path=art_path,
            content_hash=art_hash,
            size_bytes=art_size,
            delivery_status="local_only",
            approval_status=DocumentApproval.DRAFT,
            created_at=now_dt,
        )
    )

    engine.close()

    return {
        "data_root": data_root,
        "backups_dir": backups_dir,
        "config_file": config_file,
        "ops_config_file": ops_config_file,
        "job_id": job_id,
        "req_id": req_id,
        "art_id": art_id,
    }


def test_cli_capacity_json(ops_env, capsys):
    ret = main(
        [
            "ops",
            "capacity",
            "--config",
            str(ops_env["config_file"]),
            "--data-root",
            str(ops_env["data_root"]),
            "--destination",
            str(ops_env["backups_dir"]),
            "--json",
        ]
    )
    # 1 because remote capacity is unknown (SF-04 absent)
    assert ret == 1
    out, err = capsys.readouterr()
    data = json.loads(out)
    assert data["source_volume"]["status"] == "ok"
    assert data["destination_volume"] is not None
    assert data["remote_capacity"]["status"] == "unknown"


def test_cli_capacity_text(ops_env, capsys):
    ret = main(
        [
            "ops",
            "capacity",
            "--config",
            str(ops_env["config_file"]),
            "--data-root",
            str(ops_env["data_root"]),
            "--destination",
            str(ops_env["backups_dir"]),
        ]
    )
    assert ret == 1
    out, err = capsys.readouterr()
    assert "Storage Capacity Report" in out
    assert "Source Volume:" in out
    assert "Destination Volume:" in out
    assert "SF-04" in out


def test_cli_cleanup_preview_and_apply(ops_env, capsys):
    # Preview
    ret = main(
        [
            "ops",
            "cleanup",
            "preview",
            "--config",
            str(ops_env["config_file"]),
            "--data-root",
            str(ops_env["data_root"]),
            "--json",
        ]
    )
    assert ret == 0
    out, _ = capsys.readouterr()
    plan_data = json.loads(out)
    plan_id = plan_data["plan_id"]
    plan_hash = plan_data["plan_hash"]
    assert plan_data["status"] == "planned"

    # Apply with wrong hash -> exit code 2
    ret_fail = main(
        [
            "ops",
            "cleanup",
            "apply",
            "--plan",
            plan_id,
            "--plan-hash",
            "bad_hash_123",
            "--config",
            str(ops_env["config_file"]),
            "--data-root",
            str(ops_env["data_root"]),
            "--json",
        ]
    )
    assert ret_fail == 2

    # Apply with correct hash -> exit code 0
    ret_ok = main(
        [
            "ops",
            "cleanup",
            "apply",
            "--plan",
            plan_id,
            "--plan-hash",
            plan_hash,
            "--config",
            str(ops_env["config_file"]),
            "--data-root",
            str(ops_env["data_root"]),
            "--json",
        ]
    )
    assert ret_ok == 0
    out_apply, _ = capsys.readouterr()
    result_data = json.loads(out_apply)
    assert result_data["status"] == "succeeded"


def test_cli_backup_create_verify_and_restore(ops_env, capsys, tmp_path):
    # 1. Create backup with --local-only (exit code 1 because local-only is degraded coverage)
    ret_bak = main(
        [
            "ops",
            "backup",
            "create",
            "--config",
            str(ops_env["config_file"]),
            "--data-root",
            str(ops_env["data_root"]),
            "--destination",
            str(ops_env["backups_dir"]),
            "--local-only",
            "--json",
        ]
    )
    assert ret_bak == 1
    out_bak, _ = capsys.readouterr()
    bak_manifest = json.loads(out_bak)
    backup_id = bak_manifest["backup_id"]
    assert bak_manifest["completeness_status"] == "complete_local"

    # Find backup dir
    backup_dirs = [p for p in ops_env["backups_dir"].iterdir() if p.is_dir() and backup_id in p.name]
    assert len(backup_dirs) == 1
    backup_dir = backup_dirs[0]

    # 2. Verify backup
    ret_ver = main(
        [
            "ops",
            "backup",
            "verify",
            "--backup-dir",
            str(backup_dir),
            "--json",
        ]
    )
    assert ret_ver == 0
    out_ver, _ = capsys.readouterr()
    ver_data = json.loads(out_ver)
    assert ver_data["status"] == "valid"

    # Verify missing backup dir -> exit code 2
    ret_ver_missing = main(
        [
            "ops",
            "backup",
            "verify",
            "--backup-dir",
            str(tmp_path / "nonexistent_dir"),
        ]
    )
    assert ret_ver_missing == 2

    # 3. Restore Plan
    target_root = tmp_path / "restored_target_root"
    ret_plan = main(
        [
            "ops",
            "restore",
            "plan",
            "--backup-dir",
            str(backup_dir),
            "--target",
            str(target_root),
            "--config",
            str(ops_env["config_file"]),
            "--json",
        ]
    )
    assert ret_plan == 0
    out_plan, _ = capsys.readouterr()
    res_plan = json.loads(out_plan)
    assert res_plan["is_valid"] is True

    # 4. Restore Apply
    ret_res = main(
        [
            "ops",
            "restore",
            "apply",
            "--backup-dir",
            str(backup_dir),
            "--target",
            str(target_root),
            "--config",
            str(ops_env["config_file"]),
            "--json",
        ]
    )
    assert ret_res == 0
    out_res, _ = capsys.readouterr()
    res_result = json.loads(out_res)
    assert res_result["status"] == "succeeded"
    assert res_result["integrity_check_passed"] is True
    assert res_result["foreign_key_check_passed"] is True
    assert res_result["relocated_paths_count"] > 0

    # 5. Restore into already populated target -> exit code 2 (refuses non-empty target)
    ret_refuse = main(
        [
            "ops",
            "restore",
            "plan",
            "--backup-dir",
            str(backup_dir),
            "--target",
            str(target_root),
            "--config",
            str(ops_env["config_file"]),
        ]
    )
    assert ret_refuse == 2


def test_cli_invalid_command():
    with pytest.raises(SystemExit) as exc_info:
        main(["ops", "nonexistent"])
    assert exc_info.value.code == 2
