"""Tests for CLI foundation skeleton commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.cli import main


class TestCli:
    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "job_automation 0.1.0" in captured.out

    def test_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "config" in captured.out

    def test_config_check_success(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        cfg_file = tmp_path / "app.json"
        data_dir = (tmp_path / "Data Dir Space ä").resolve()
        cfg_content = {
            "schema_version": "1.0",
            "app_name": "JobAutomation",
            "data_root": str(data_dir),
            "display_timezone": "Europe/Berlin",
            "model_service_url": "http://127.0.0.1:11434",
        }
        cfg_file.write_text(json.dumps(cfg_content), encoding="utf-8")

        exit_code = main(["config", "check", "--config", str(cfg_file)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Configuration check: VALID" in captured.out
        assert "Europe/Berlin" in captured.out

    def test_config_check_missing_file_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["config", "check", "--config", "does_not_exist_file.json"])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Configuration check: FAILED" in captured.err

    def test_config_check_redacts_secret_sentinel(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg_file = tmp_path / "malformed.json"
        # Include SECRET_SENTINEL in malformed JSON or invalid setting
        cfg_file.write_text('{"display_timezone": "SECRET_SENTINEL"}', encoding="utf-8")

        exit_code = main(["config", "check", "--config", str(cfg_file)])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "SECRET_SENTINEL" not in captured.err
        assert "[REDACTED]" in captured.err or "Configuration check: FAILED" in captured.err

