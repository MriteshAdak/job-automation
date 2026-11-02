"""Tests for sources CLI commands: sources list and sources check (SOURCE-01-S07)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_EXAMPLE = REPO_ROOT / "config" / "app.example.json"
SOURCES_EXAMPLE = REPO_ROOT / "config" / "sources.example.json"
VALID_REGISTRY = REPO_ROOT / "tests" / "fixtures" / "sources" / "valid_registry.json"


class TestSourcesCLI:
    def test_sources_list_with_config(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify 'sources list --config' prints configured sources and exits 0."""
        ret = main(["sources", "list", "--config", str(CONFIG_EXAMPLE)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Configured Sources (5):" in captured.out
        assert "arbeitnow_de" in captured.out
        assert "greenhouse_board_synthetic" in captured.out

    def test_sources_list_with_registry_direct(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify 'sources list --registry' directly loads registry file."""
        ret = main(["sources", "list", "--registry", str(SOURCES_EXAMPLE)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Configured Sources (5):" in captured.out

    def test_sources_list_as_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify 'sources list --json' produces parseable JSON with source details."""
        ret = main(["sources", "list", "--config", str(CONFIG_EXAMPLE), "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["source_count"] == 5
        assert len(data["sources"]) == 5
        first = data["sources"][0]
        assert "source_key" in first
        assert "scope_id" in first
        assert "is_runnable" in first

    def test_sources_check_default_empty_selection_valid(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify 'sources check --config' with active_sources=[] succeeds with exit 0."""
        ret = main(["sources", "check", "--config", str(CONFIG_EXAMPLE)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Sources check: VALID" in captured.out
        assert "Selected Count:    0" in captured.out

    def test_sources_check_disabled_source_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify 'sources check' selecting a disabled source exits 2 with blocker."""
        ret = main(["sources", "check", "--config", str(CONFIG_EXAMPLE), "--source", "arbeitnow_de"])
        assert ret == 2
        captured = capsys.readouterr()
        assert "Sources check: FAILED" in captured.err
        assert "disabled" in captured.err

    def test_sources_check_unconfigured_source_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify 'sources check' selecting an unknown key exits 2."""
        ret = main(["sources", "check", "--config", str(CONFIG_EXAMPLE), "--source", "nonexistent"])
        assert ret == 2
        captured = capsys.readouterr()
        assert "Sources check: FAILED" in captured.err
        assert "not configured" in captured.err

    def test_sources_check_valid_enabled_source_passes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify 'sources check' on valid enabled fixture exits 0."""
        ret = main(
            [
                "sources",
                "check",
                "--registry",
                str(VALID_REGISTRY),
                "--source",
                "fixture_api_board",
            ]
        )
        assert ret == 0
        captured = capsys.readouterr()
        assert "Sources check: VALID" in captured.out
        assert "Selected Count:    1" in captured.out
        assert "fixture_api_board" in captured.out

    def test_sources_check_duplicate_sources_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify 'sources check' with duplicate explicit --source keys exits 2."""
        ret = main(
            [
                "sources",
                "check",
                "--registry",
                str(VALID_REGISTRY),
                "--source",
                "fixture_api_board",
                "--source",
                "fixture_api_board",
            ]
        )
        assert ret == 2
        captured = capsys.readouterr()
        assert "Sources check: FAILED" in captured.err
        assert "Duplicate" in captured.err

    def test_sources_check_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify 'sources check --json' returns JSON payload and correct exit code."""
        ret_ok = main(
            [
                "sources",
                "check",
                "--registry",
                str(VALID_REGISTRY),
                "--source",
                "fixture_api_board",
                "--json",
            ]
        )
        assert ret_ok == 0
        captured_ok = capsys.readouterr()
        data_ok = json.loads(captured_ok.out)
        assert data_ok["is_valid"] is True
        assert data_ok["selected_count"] == 1

        ret_fail = main(
            [
                "sources",
                "check",
                "--registry",
                str(VALID_REGISTRY),
                "--source",
                "fixture_manual_pasted",
                "--json",
            ]
        )
        assert ret_fail == 2
        captured_fail = capsys.readouterr()
        data_fail = json.loads(captured_fail.out)
        assert data_fail["is_valid"] is False
        assert len(data_fail["blockers"]) >= 1

    def test_sources_check_missing_registry_file(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Verify missing registry file exits 2 with safe error."""
        missing = tmp_path / "nonexistent_registry.json"
        ret = main(["sources", "check", "--registry", str(missing)])
        assert ret == 2
        captured = capsys.readouterr()
        assert "FAILED" in captured.err or "FAILED" in captured.out

