"""Tests for availability policy, settings validation, and override precedence (IDENTITY-02-S01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.identity.availability.errors import AvailabilityConfigurationError
from job_automation.identity.availability.settings import (
    AvailabilityPolicy,
    AvailabilityRuleSettings,
    load_availability_policy,
)


class TestSettings:
    def test_default_rules(self) -> None:
        policy = AvailabilityPolicy()
        assert policy.default_rules.consecutive_complete_misses == 3
        assert policy.default_rules.grace_seconds == 172800.0
        assert policy.fingerprint.startswith("sha256:")

    def test_consecutive_misses_rejects_boolean(self) -> None:
        with pytest.raises(AvailabilityConfigurationError, match="cannot be a boolean"):
            AvailabilityRuleSettings(consecutive_complete_misses=True)  # type: ignore

        with pytest.raises(AvailabilityConfigurationError, match="cannot be a boolean"):
            AvailabilityRuleSettings(consecutive_complete_misses=False)  # type: ignore

    def test_consecutive_misses_rejects_less_than_two(self) -> None:
        with pytest.raises(AvailabilityConfigurationError, match="must be at least 2"):
            AvailabilityRuleSettings(consecutive_complete_misses=1)

        with pytest.raises(AvailabilityConfigurationError, match="must be at least 2"):
            AvailabilityRuleSettings(consecutive_complete_misses=0)

    def test_grace_seconds_rejects_negative_or_infinite(self) -> None:
        with pytest.raises(AvailabilityConfigurationError, match="finite non-negative"):
            AvailabilityRuleSettings(grace_seconds=-10.0)

        with pytest.raises(AvailabilityConfigurationError, match="finite non-negative"):
            AvailabilityRuleSettings(grace_seconds=float("inf"))

        with pytest.raises(AvailabilityConfigurationError, match="finite non-negative"):
            AvailabilityRuleSettings(grace_seconds=float("nan"))

    def test_override_precedence(self) -> None:
        policy = AvailabilityPolicy(
            default_rules=AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=1000.0),
            source_overrides={
                "src_fast": AvailabilityRuleSettings(consecutive_complete_misses=2, grace_seconds=500.0),
            },
            scope_overrides={
                "scope_special": AvailabilityRuleSettings(consecutive_complete_misses=4, grace_seconds=2000.0),
            },
        )

        # 1. Unmatched -> default
        r1 = policy.get_effective_rules(source_key="src_other", scope_id="scope_other")
        assert r1.consecutive_complete_misses == 3
        assert r1.grace_seconds == 1000.0

        # 2. Source match -> source override
        r2 = policy.get_effective_rules(source_key="src_fast", scope_id="scope_other")
        assert r2.consecutive_complete_misses == 2
        assert r2.grace_seconds == 500.0

        # 3. Scope match beats source match
        r3 = policy.get_effective_rules(source_key="src_fast", scope_id="scope_special")
        assert r3.consecutive_complete_misses == 4
        assert r3.grace_seconds == 2000.0

    def test_deterministic_fingerprint(self) -> None:
        p1 = AvailabilityPolicy(
            default_rules=AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=100.0)
        )
        p2 = AvailabilityPolicy(
            default_rules=AvailabilityRuleSettings(consecutive_complete_misses=3, grace_seconds=100.0)
        )
        p3 = AvailabilityPolicy(
            default_rules=AvailabilityRuleSettings(consecutive_complete_misses=2, grace_seconds=100.0)
        )

        assert p1.fingerprint == p2.fingerprint
        assert p1.fingerprint != p3.fingerprint

    def test_load_policy_from_file_and_dict(self, tmp_path: Path) -> None:
        data = {
            "policy_version": "2.0",
            "default_rules": {
                "consecutive_complete_misses": 5,
                "grace_seconds": 86400.0,
            },
        }
        loaded_dict = load_availability_policy(data)
        assert loaded_dict.policy_version == "2.0"
        assert loaded_dict.default_rules.consecutive_complete_misses == 5

        file_path = tmp_path / "policy.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        loaded_file = load_availability_policy(file_path)
        assert loaded_file.policy_version == "2.0"
        assert loaded_file.default_rules.grace_seconds == 86400.0

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AvailabilityConfigurationError, match="not found"):
            load_availability_policy(tmp_path / "nonexistent.json")

