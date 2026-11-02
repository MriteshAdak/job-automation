"""Tests for CLI parsing and dispatch (RUN-01-S08)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.cli import create_parser, main
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine


class TestCli:
    def test_run_parser_help_and_subcommands(self) -> None:
        parser = create_parser()

        # Test run start arguments
        args_start = parser.parse_args(["run", "start", "--assessment-mode", "rules", "--no-sync", "--json"])
        assert args_start.command == "run"
        assert args_start.run_command == "start"
        assert args_start.assessment_mode == "rules"
        assert args_start.no_sync is True
        assert args_start.json is True

        # Test run resume arguments
        run_uuid = str(uuid.uuid4())
        args_resume = parser.parse_args(["run", "resume", "--run-id", run_uuid])
        assert args_resume.command == "run"
        assert args_resume.run_command == "resume"
        assert args_resume.run_id == run_uuid

        # Test run show arguments
        args_show = parser.parse_args(["run", "show", "--run-id", run_uuid, "--json"])
        assert args_show.command == "run"
        assert args_show.run_command == "show"
        assert args_show.run_id == run_uuid
        assert args_show.json is True

    def test_show_nonexistent_run_returns_code_1(self, tmp_path: Path) -> None:
        random_uuid = str(uuid.uuid4())
        ret = main(["run", "show", "--run-id", random_uuid, "--data-root", str(tmp_path)])
        assert ret == 1

    def test_show_existing_run_with_json_outputs_valid_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db_path = tmp_path / "database" / "job_automation.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        summary = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status="success",
            source_counts={"arbeitnow:berlin": 5},
            source_postings_count=5,
            canonical_jobs_new=2,
        )
        engine.runs.complete_run(summary)
        engine.close()

        ret = main(["run", "show", "--run-id", str(run_id), "--data-root", str(tmp_path), "--json"])
        assert ret == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["c15_summary"]["run_id"] == str(run_id)
        assert data["c15_summary"]["status"] == "success"
        assert data["c15_summary"]["canonical_jobs_new"] == 2

    def test_lock_busy_returns_code_3(self, tmp_path: Path) -> None:
        # Hold lock externally
        lock = WindowsWorkerLock(tmp_path)
        token = lock.acquire_lock()
        try:
            ret = main(["run", "start", "--data-root", str(tmp_path)])
            assert ret == 3
        finally:
            token.release()

    def test_nonexistent_run_config_returns_code_2(self, tmp_path: Path) -> None:
        """GAP 1: Nonexistent explicit run-config file fails with code 2."""
        ret = main(["run", "start", "--data-root", str(tmp_path), "--run-config", str(tmp_path / "nonexistent.json")])
        assert ret == 2

    def test_strategy_flag_alias(self) -> None:
        """GAP 1: Both --strategy and --llm-strategy are accepted."""
        parser = create_parser()
        args1 = parser.parse_args(["run", "start", "--strategy", "rag"])
        assert args1.llm_strategy == "rag"
        args2 = parser.parse_args(["run", "start", "--llm-strategy", "json"])
        assert args2.llm_strategy == "json"
