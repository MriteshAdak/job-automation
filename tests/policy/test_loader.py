"""Tests for POLICY-01-S02 safe local C02 loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.policy.loader import load_policy_dict


class TestPolicyLoader:
    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        data, explicit_missing, issues, err = load_policy_dict(missing)
        assert data is None
        assert err is not None
        assert err.category == ErrorCategory.MISSING_CONFIGURATION
        assert any(i.code == "missing_policy_file" for i in issues)

    def test_load_utf8_with_and_without_bom(self, tmp_path: Path) -> None:
        policy_dict = {
            "schema_version": "1.0",
            "policy_version": "bom-test-v1",
            "regions": ["DE"],
            "role_aliases": {"Entwickler": ["Developer"]},
        }
        json_text = json.dumps(policy_dict)

        # Write plain UTF-8
        plain_file = tmp_path / "plain_utf8.json"
        plain_file.write_text(json_text, encoding="utf-8")

        # Write UTF-8 with BOM
        bom_file = tmp_path / "bom_utf8.json"
        bom_file.write_text(json_text, encoding="utf-8-sig")

        data_plain, _, issues_plain, err_plain = load_policy_dict(plain_file)
        data_bom, _, issues_bom, err_bom = load_policy_dict(bom_file)

        assert err_plain is None
        assert err_bom is None
        assert data_plain == policy_dict
        assert data_bom == policy_dict
        assert len(issues_plain) == 0
        assert len(issues_bom) == 0

    def test_load_invalid_encoding(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad_encoding.json"
        # Write invalid UTF-8 byte sequence
        bad_file.write_bytes(b"\xff\xfe\x00\x00invalid")

        data, _, issues, err = load_policy_dict(bad_file)
        assert data is None
        assert err is not None
        assert err.category == ErrorCategory.UNSUPPORTED_INPUT
        assert any(i.code == "invalid_encoding" for i in issues)

    def test_reject_duplicate_json_keys(self, tmp_path: Path) -> None:
        dup_file = tmp_path / "duplicate_keys.json"
        dup_file.write_text(
            '{"schema_version": "1.0", "policy_version": "v1", "regions": ["DE"], "regions": ["AT"]}',
            encoding="utf-8",
        )
        data, _, issues, err = load_policy_dict(dup_file)
        assert data is None
        assert err is not None
        assert any(i.code == "duplicate_json_key" for i in issues)

    def test_reject_non_dict_root(self, tmp_path: Path) -> None:
        list_file = tmp_path / "list_root.json"
        list_file.write_text('[{"schema_version": "1.0"}]', encoding="utf-8")

        data, _, issues, err = load_policy_dict(list_file)
        assert data is None
        assert err is not None
        assert any(i.code == "invalid_root_type" for i in issues)

    def test_reject_unsupported_schema_version(self, tmp_path: Path) -> None:
        v2_file = tmp_path / "v2.json"
        v2_file.write_text('{"schema_version": "2.0", "policy_version": "v1"}', encoding="utf-8")

        data, _, issues, err = load_policy_dict(v2_file)
        assert data is None
        assert err is not None
        assert err.category == ErrorCategory.UNSUPPORTED_INPUT
        assert any(i.code == "unsupported_schema_version" for i in issues)

    def test_explicit_on_missing_preservation(self, tmp_path: Path) -> None:
        content = {
            "schema_version": "1.0",
            "policy_version": "on-missing-test",
            "regions": ["DE"],
            "hard_criteria": [
                {
                    "criterion_id": "c_explicit",
                    "name": "Explicit unknown",
                    "field": "workplace_type",
                    "operator": "equals",
                    "expected_value": "remote",
                    "on_missing": "unknown",
                },
                {
                    "criterion_id": "c_omitted",
                    "name": "Omitted on_missing",
                    "field": "workplace_type",
                    "operator": "equals",
                    "expected_value": "remote",
                },
            ],
        }
        test_file = tmp_path / "on_missing.json"
        test_file.write_text(json.dumps(content), encoding="utf-8")

        data, explicit_missing, issues, err = load_policy_dict(test_file)
        assert err is None
        assert data is not None
        assert explicit_missing.get("c_explicit") is True
        assert explicit_missing.get("c_omitted") is False

    def test_safe_error_messages_no_secret_leak(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "secret.json"
        # File with syntax error near secret marker
        secret_file.write_text('{"schema_version": "1.0", "secret": SECRET_TOKEN_XYZ,}', encoding="utf-8")

        data, _, issues, err = load_policy_dict(secret_file)
        assert data is None
        assert err is not None
        assert "SECRET_TOKEN_XYZ" not in err.message
        for issue in issues:
            assert "SECRET_TOKEN_XYZ" not in issue.message

