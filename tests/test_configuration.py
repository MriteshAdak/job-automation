"""Tests for application configuration and path resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.configuration import AppConfig, load_config


class TestConfiguration:
    def test_valid_configuration_resolution(self, tmp_path: Path) -> None:
        data_root = (tmp_path / "Job Automation Daten").resolve()
        config = AppConfig(
            data_root=str(data_root),
            display_timezone="Europe/Berlin",
            active_policy_ref="policy.json",
            model_service_url="http://127.0.0.1:11434",
        )
        paths = config.resolve_paths(base_dir=tmp_path)

        assert paths.data_root == data_root
        assert paths.profiles_dir == data_root / "profiles"
        assert paths.database_path == data_root / "database" / "job_automation.db"
        assert paths.policy_path == tmp_path / "policy.json"

    def test_relative_data_root_fails(self) -> None:
        config = AppConfig(data_root="relative/path/to/data")
        with pytest.raises(ValueError, match="must be an absolute path"):
            config.resolve_paths()

    def test_data_root_inside_repo_fails(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        inside_path = repo_root / "runtime_data"
        config = AppConfig(data_root=str(inside_path))
        with pytest.raises(ValueError, match="strictly outside repository"):
            config.resolve_paths()

    def test_non_loopback_model_service_fails(self) -> None:
        with pytest.raises(ValidationError, match="loopback"):
            AppConfig(
                data_root="C:\\Data",
                model_service_url="http://api.openai.com/v1",
            )

    def test_invalid_timezone_fails(self) -> None:
        with pytest.raises(ValidationError, match="Invalid IANA timezone"):
            AppConfig(
                data_root="C:\\Data",
                display_timezone="Invalid/Timezone",
            )

    def test_load_config_from_file_with_spaces_and_umlauts(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "test_app_ä.json"
        data_dir = (tmp_path / "Job Automation Prüfung ä").resolve()

        cfg_content = {
            "schema_version": "1.0",
            "app_name": "JobAutomationTest",
            "data_root": str(data_dir),
            "display_timezone": "Europe/Berlin",
            "model_service_url": "http://localhost:11434",
        }
        cfg_file.write_text(json.dumps(cfg_content), encoding="utf-8")

        config, paths = load_config(config_path=cfg_file)
        assert config.app_name == "JobAutomationTest"
        assert paths.data_root == data_dir

