"""Unit tests for operations settings loading and policy fingerprinting (OPS-01-S02)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from job_automation.operations.records import OperationsSettings
from job_automation.operations.settings import (
    compute_policy_fingerprint,
    load_operations_settings,
)


def test_load_default_settings() -> None:
    settings = load_operations_settings(None)
    assert settings.retention.enabled is False
    assert settings.retention.raw_payloads_days == 90
    assert settings.backup.keep_generations == 3


def test_load_example_operations_settings() -> None:
    example_path = Path(__file__).resolve().parent.parent.parent / "config" / "operations.example.json"
    settings = load_operations_settings(example_path)
    assert settings.schema_version == "1.0"
    assert settings.retention.enabled is False
    assert settings.retention.source_overrides.get("arbeitnow") == 90


def test_policy_fingerprint_changes_on_modification() -> None:
    s1 = OperationsSettings()
    fp1 = compute_policy_fingerprint(s1)

    s2 = OperationsSettings(
        retention={"enabled": True, "raw_payloads_days": 180}
    )
    fp2 = compute_policy_fingerprint(s2)

    assert fp1 != fp2

    # Deterministic for identical settings
    s3 = OperationsSettings(
        retention={"enabled": True, "raw_payloads_days": 180}
    )
    assert compute_policy_fingerprint(s3) == fp2


def test_invalid_settings_validation(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_ops.json"
    bad_file.write_text(json.dumps({"capacity": {"reserve_percent": 150.0}}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_operations_settings(bad_file)

