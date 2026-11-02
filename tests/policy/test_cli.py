"""Tests for POLICY-01-S07 CLI policy check command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


class TestPolicyCLI:
    @pytest.fixture
    def python_exe(self) -> str:
        return sys.executable

    def test_cli_help_and_subcommand_help(self, python_exe: str) -> None:
        cmd1 = [python_exe, "-m", "job_automation", "policy", "--help"]
        p1 = subprocess.run(cmd1, capture_output=True, text=True)
        assert p1.returncode == 0
        assert "check" in p1.stdout

        cmd2 = [python_exe, "-m", "job_automation", "policy", "check", "--help"]
        p2 = subprocess.run(cmd2, capture_output=True, text=True)
        assert p2.returncode == 0
        assert "--policy" in p2.stdout
        assert "--config" in p2.stdout
        assert "--json" in p2.stdout

    def test_check_valid_policy_direct_path(self, python_exe: str) -> None:
        policy_path = Path("config/policy.example.json").resolve()
        cmd = [python_exe, "-m", "job_automation", "policy", "check", "--policy", str(policy_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert "Policy check: VALID" in res.stdout
        assert "policy-v1:sha256:" in res.stdout

    def test_check_valid_office_policy_direct_path(self, python_exe: str) -> None:
        policy_path = Path("config/policy.office.example.json").resolve()
        cmd = [python_exe, "-m", "job_automation", "policy", "check", "--policy", str(policy_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        assert "Policy check: VALID" in res.stdout
        assert "policy-v1:sha256:" in res.stdout

    def test_check_valid_policy_json_mode(self, python_exe: str) -> None:
        policy_path = Path("config/policy.example.json").resolve()
        cmd = [python_exe, "-m", "job_automation", "policy", "check", "--policy", str(policy_path), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert data["is_valid"] is True
        assert data["fingerprint"].startswith("policy-v1:sha256:")
        assert data["schema_version"] == "1.0"
        assert len(data["issues"]) == 0

    def test_check_via_app_config_reference(self, python_exe: str, tmp_path: Path) -> None:
        policy_path = Path("config/policy.example.json").resolve()
        policy_copy = tmp_path / "my_policy.json"
        policy_copy.write_text(policy_path.read_text(encoding="utf-8"), encoding="utf-8")

        config_file = tmp_path / "app.json"
        data_root = tmp_path / "DataRoot"
        config_content = {
            "schema_version": "1.0",
            "data_root": str(data_root),
            "active_policy_ref": "my_policy.json",
        }
        config_file.write_text(json.dumps(config_content), encoding="utf-8")

        cmd = [python_exe, "-m", "job_automation", "policy", "check", "--config", str(config_file), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert data["is_valid"] is True

        # Policy check should NOT create the data_root directory
        assert not data_root.exists()

    def test_mutually_exclusive_arguments(self, python_exe: str) -> None:
        # Both --policy and --config
        cmd1 = [
            python_exe, "-m", "job_automation", "policy", "check",
            "--policy", "config/policy.example.json",
            "--config", "config/app.example.json",
        ]
        res1 = subprocess.run(cmd1, capture_output=True, text=True)
        assert res1.returncode == 2

        # Neither --policy nor --config
        cmd2 = [python_exe, "-m", "job_automation", "policy", "check"]
        res2 = subprocess.run(cmd2, capture_output=True, text=True)
        assert res2.returncode == 2

    def test_missing_policy_file_fails_with_exit_code_2(self, python_exe: str) -> None:
        cmd = [python_exe, "-m", "job_automation", "policy", "check", "--policy", "nonexistent_policy.json", "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 2
        data = json.loads(res.stdout)
        assert data["is_valid"] is False
        assert data["fingerprint"] is None
        assert any(i["code"] == "missing_policy_file" for i in data["issues"])

    def test_invalid_policy_fails_with_exit_code_2(self, python_exe: str) -> None:
        policy_path = Path("tests/fixtures/policy/invalid_contradictory_hard.json").resolve()
        cmd = [python_exe, "-m", "job_automation", "policy", "check", "--policy", str(policy_path), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 2
        data = json.loads(res.stdout)
        assert data["is_valid"] is False
        assert any(i["code"] == "contradictory_hard_criteria" for i in data["issues"])

    def test_warning_policy_exits_0_with_visible_warnings(self, python_exe: str) -> None:
        policy_path = Path("tests/fixtures/policy/warning_unreachable_preference.json").resolve()
        cmd = [python_exe, "-m", "job_automation", "policy", "check", "--policy", str(policy_path), "--json"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert data["is_valid"] is True
        assert any(i["severity"] == "warning" and i["code"] == "unreachable_preference" for i in data["issues"])

