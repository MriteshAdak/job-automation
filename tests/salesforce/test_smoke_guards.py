"""Tests for salesforce_smoke.py guards, read-only defaults, and missing prerequisite reporting (SFCLIENT-01-S07)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tests.manual.salesforce_smoke import run_smoke


def test_smoke_reports_pending_without_config(capsys) -> None:
    """Verify smoke script reports pending status when run without config."""
    code = run_smoke(config_path=None)
    captured = capsys.readouterr().out
    assert code == 0
    assert "PREREQUISITE STATUS" in captured
    assert "SF-02 handoff absent" in captured


def test_smoke_reports_pending_when_salesforce_settings_ref_absent(tmp_path: Path, capsys) -> None:
    """Verify smoke script reports pending when AppConfig lacks salesforce_settings_ref."""
    app_cfg = tmp_path / "app.json"
    app_cfg.write_text(
        json.dumps({
            "schema_version": "1.0",
            "app_name": "JobAutomationTest",
            "data_root": str(tmp_path / "runtime_data"),
        }),
        encoding="utf-8",
    )

    code = run_smoke(config_path=app_cfg)
    captured = capsys.readouterr().out
    assert code == 0
    assert "PREREQUISITE STATUS" in captured
    assert "No salesforce_settings_ref configured" in captured


def test_smoke_rejects_mutation_without_synthetic_prefix(tmp_path: Path, capsys) -> None:
    """Verify smoke script rejects write check if test_key lacks SYNTHETIC_TEST_ prefix."""
    sf_cfg = tmp_path / "sf.json"
    sf_cfg.write_text(
        json.dumps({
            "schema_version": "1.0",
            "instance_url": "https://test.my.salesforce.com",
            "client_id_ref": "cid",
            "credential_ref": "cred",
        }),
        encoding="utf-8",
    )

    # Missing synthetic prefix
    code = run_smoke(
        config_path=sf_cfg,
        allow_write=True,
        test_key="REAL_JOB_123",
    )
    captured = capsys.readouterr().out
    assert code == 2
    assert "must begin with 'SYNTHETIC_TEST_' prefix" in captured

