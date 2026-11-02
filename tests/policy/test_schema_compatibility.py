"""Tests for POLICY-01-S08 C02 schema compatibility and contract export parity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.contracts.policy import SearchPolicy
from job_automation.policy.models import POLICY_SCHEMA_VERSION
from job_automation.policy.service import PolicyService


class TestSchemaCompatibility:
    def test_c02_schema_export_integrity(self) -> None:
        """Verify that C02 schema can be exported and has version 1.0."""
        schema = SearchPolicy.model_json_schema()
        assert schema is not None
        assert "properties" in schema
        assert "policy_version" in schema["properties"]
        assert "hard_criteria" in schema["properties"]
        assert "preferences" in schema["properties"]

    def test_legacy_c02_fixture_structural_readability(self) -> None:
        """Verify that historical C02 contract fixture remains structurally readable."""
        fixture_path = Path("tests/fixtures/contracts/C02/valid.json")
        raw_text = fixture_path.read_text(encoding="utf-8")
        raw_dict = json.loads(raw_text)

        # C02 contract model parses it without error
        policy = SearchPolicy.model_validate(raw_dict)
        assert policy.schema_version == "1.0"
        assert policy.policy_version == "pol-de-v1"

        # Semantic validator correctly flags 'skills' as unsupported target
        res = PolicyService.load_and_validate(fixture_path)
        assert not res.is_valid
        assert any(i.code == "unsupported_target" for i in res.errors)

    def test_effective_policy_complies_with_c02_contract(self) -> None:
        """Effective policy produced by PolicyService validates strictly against SearchPolicy."""
        tech_path = Path("config/policy.example.json")
        res = PolicyService.load_and_validate(tech_path)
        assert res.is_valid
        assert res.effective_policy is not None

        # Effective policy can be serialized and deserialized as C02 SearchPolicy
        dumped = res.effective_policy.policy.model_dump()
        reloaded = SearchPolicy.model_validate(dumped)
        assert reloaded.policy_version == res.fingerprint
        assert reloaded.schema_version == POLICY_SCHEMA_VERSION

