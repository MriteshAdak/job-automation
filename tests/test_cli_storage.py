"""Tests for CLI storage commands (migrate, status)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.cli import main


class TestCliStorage:
    def test_cli_storage_migrate_and_status(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg_file = tmp_path / "app.json"
        data_dir = (tmp_path / "Runtime Data").resolve()
        cfg_content = {
            "schema_version": "1.0",
            "app_name": "JobAutomation",
            "data_root": str(data_dir),
            "display_timezone": "Europe/Berlin",
            "model_service_url": "http://127.0.0.1:11434",
        }
        cfg_file.write_text(json.dumps(cfg_content), encoding="utf-8")

        # 1. Run migrate command
        exit_code = main(["storage", "migrate", "--config", str(cfg_file)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Storage migration: SUCCESS" in captured.out
        assert "Current Version:   18" in captured.out

        # 2. Run status command
        exit_code = main(["storage", "status", "--config", str(cfg_file)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Storage status: OK" in captured.out
        assert "Current Version:   18" in captured.out
        assert "Applied Count:     18" in captured.out
        assert "v1 (001_initial)" in captured.out
        assert "v2 (002_stage_checkpoints_and_audit)" in captured.out
        assert "v3 (003_profile_evidence_and_snapshots)" in captured.out
        assert "v4 (004_identity_tracking_and_lineage)" in captured.out
        assert "v5 (005_availability_tracking)" in captured.out
        assert "v6 (006_context_indexes)" in captured.out
        assert "v7 (007_sync_lifecycle_and_ordering)" in captured.out
        assert "v8 (008_pipeline_work_and_run_attempts)" in captured.out
        assert "v9 (009_operations_journal_and_plans)" in captured.out
        assert "v10 (010_generation_workflow_and_checkpoints)" in captured.out
        assert "v11 (011_frozen_inputs_and_preflight)" in captured.out
        assert "v12 (012_draft_content)" in captured.out
        assert "v13 (013_document_validation)" in captured.out
        assert "v14 (014_render_artifacts)" in captured.out
        assert "v15 (015_artifact_deliveries)" in captured.out
        assert "v16 (016_scheduling_occurrences_and_launches)" in captured.out
        assert "v17 (017_automatic_draft_policy_and_history)" in captured.out
        assert "v18 (018_run_summary_deliveries)" in captured.out

    def test_cli_storage_migrate_missing_config_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["storage", "migrate", "--config", "nonexistent_config.json"])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Storage migration: FAILED" in captured.err

