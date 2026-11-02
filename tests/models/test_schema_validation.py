"""Tests for strict JSON parsing and schema validation rules (LLM-01-S04)."""

from __future__ import annotations

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.models.schemas import (
    LocalSchemaRegistry,
    parse_strict_json,
    validate_against_schema,
)


class TestSchemaValidation:
    def test_strict_json_rejects_duplicate_keys(self) -> None:
        """JSON with duplicate keys must be rejected."""
        raw = '{"key": 1, "key": 2}'
        with pytest.raises(ValueError, match="Duplicate key in JSON object"):
            parse_strict_json(raw)

    def test_strict_json_rejects_nan_and_infinity(self) -> None:
        """JSON with NaN or Infinity must be rejected."""
        with pytest.raises(ValueError, match="Non-finite numbers"):
            parse_strict_json('{"val": NaN}')

        with pytest.raises(ValueError, match="Non-finite numbers"):
            parse_strict_json('{"val": Infinity}')

    def test_strict_json_rejects_markdown_code_fences(self) -> None:
        """Raw text wrapped in markdown fences must be rejected."""
        raw = '```json\n{"ok": true}\n```'
        with pytest.raises(ValueError, match="Markdown code fences"):
            parse_strict_json(raw)

    def test_strict_json_rejects_surrounding_prose(self) -> None:
        """Raw text with leading or trailing non-JSON prose must be rejected."""
        leading = 'Here is the JSON output: {"ok": true}'
        with pytest.raises(ValueError, match="must be a single object enclosed in"):
            parse_strict_json(leading)

        trailing = '{"ok": true} Hope this helps!'
        with pytest.raises(ValueError, match="must be a single object enclosed in|Trailing data"):
            parse_strict_json(trailing)

    def test_strict_json_rejects_non_dict_top_level(self) -> None:
        """Top-level arrays, strings, or numbers are rejected."""
        with pytest.raises(ValueError, match="must be a single object"):
            parse_strict_json('[1, 2, 3]')

        with pytest.raises(ValueError, match="must be a single object"):
            parse_strict_json('"just a string"')

    def test_strict_json_enforces_max_depth(self) -> None:
        """Deeply nested structures exceeding max_depth are rejected."""
        deep = '{"a": {"b": {"c": {"d": 1}}}}'
        with pytest.raises(ValueError, match="nesting depth exceeds"):
            parse_strict_json(deep, max_depth=3)

    def test_schema_validation_rejects_extra_fields(self) -> None:
        """Extra fields outside contract model are strictly rejected."""
        registry = LocalSchemaRegistry()
        reg_schema = registry.register("C11_assessment", Assessment)

        data = {
            "schema_version": "1.0",
            "assessment_id": "11111111-1111-4111-8111-111111111111",
            "canonical_job_id": "22222222-2222-4222-8222-222222222222",
            "posting_revision": "rev-1",
            "profile_version": "v1",
            "policy_version": "p1",
            "assessment_method": "rules",
            "rule_outcomes": [],
            "relevance_decision": "review",
            "summary_reason": "Needs review",
            "final_disposition": "review",
            "unauthorized_field": "hacked",  # Extra field!
        }

        validated, issues = validate_against_schema(data, reg_schema)
        assert validated is None
        assert len(issues) > 0
        assert any("extra_forbidden" in issue.code or "unauthorized_field" in issue.field_path for issue in issues)

    def test_schema_validation_rejects_missing_required_fields(self) -> None:
        """Missing required fields produce structured validation issues."""
        registry = LocalSchemaRegistry()
        reg_schema = registry.register("C11_assessment", Assessment)

        # Missing canonical_job_id and final_disposition
        data = {
            "schema_version": "1.0",
            "assessment_id": "11111111-1111-4111-8111-111111111111",
            "posting_revision": "rev-1",
            "profile_version": "v1",
            "policy_version": "p1",
            "assessment_method": "rules",
            "rule_outcomes": [],
        }

        validated, issues = validate_against_schema(data, reg_schema)
        assert validated is None
        assert len(issues) > 0
