"""Tests for POLICY-01-S06 deterministic fingerprinting and version binding."""

from __future__ import annotations

import copy
import json

import pytest

from job_automation.policy.validation import validate_policy_dict


class TestPolicyFingerprint:
    @pytest.fixture
    def base_policy_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "policy_version": "authored-label-v1",
            "regions": ["DE"],
            "role_aliases": {
                "Software Engineer": ["Backend Developer"]
            },
            "skill_aliases": {
                "Python": ["Python 3"]
            },
            "hard_criteria": [
                {
                    "criterion_id": "c1",
                    "name": "Remote or Hybrid",
                    "field": "workplace_type",
                    "operator": "in",
                    "expected_value": ["remote", "hybrid"],
                    "on_missing": "unknown",
                }
            ],
            "preferences": [
                {
                    "rule_id": "p1",
                    "name": "Prefer Remote",
                    "field": "workplace_type",
                    "weight": 0.8,
                    "preferred_values": ["remote"],
                }
            ],
            "exclusions": ["Gambling"],
            "missing_information_behavior": {
                "compensation": "unknown"
            },
            "relevance_configuration": {
                "score_scale": "0-100",
                "min_score_threshold": 70.0,
                "broad_keywords": ["Python"],
                "negative_keywords": ["Unpaid"],
            },
            "primary_context_strategy": "json",
        }

    def test_fingerprint_format_and_stability(self, base_policy_dict: dict) -> None:
        res1 = validate_policy_dict(base_policy_dict)
        res2 = validate_policy_dict(base_policy_dict)

        assert res1.is_valid
        assert res1.fingerprint is not None
        assert res1.fingerprint.startswith("policy-v1:sha256:")
        assert len(res1.fingerprint.split(":")[-1]) == 64
        assert res1.fingerprint == res2.fingerprint

    def test_authored_version_change_does_not_change_fingerprint(self, base_policy_dict: dict) -> None:
        """Fingerprint captures effective behavior; changing display label alone does not change fingerprint."""
        d1 = copy.deepcopy(base_policy_dict)
        d2 = copy.deepcopy(base_policy_dict)
        d1["policy_version"] = "authored-label-v1"
        d2["policy_version"] = "new-label-2026-v99"

        res1 = validate_policy_dict(d1)
        res2 = validate_policy_dict(d2)

        assert res1.is_valid and res2.is_valid
        assert res1.fingerprint == res2.fingerprint
        # Metadata preserves distinct authored versions
        assert res1.effective_policy.metadata.authored_version == "authored-label-v1"
        assert res2.effective_policy.metadata.authored_version == "new-label-2026-v99"

    def test_crlf_vs_lf_and_json_whitespace_invariance(self, base_policy_dict: dict) -> None:
        """Different whitespace and line endings produce identical fingerprint."""
        json_standard = json.dumps(base_policy_dict)
        json_pretty_crlf = json.dumps(base_policy_dict, indent=4).replace("\n", "\r\n")

        d_std = json.loads(json_standard)
        d_crlf = json.loads(json_pretty_crlf)

        res_std = validate_policy_dict(d_std)
        res_crlf = validate_policy_dict(d_crlf)

        assert res_std.fingerprint == res_crlf.fingerprint

    def test_sensitivity_matrix_every_meaningful_field_changes_fingerprint(
        self, base_policy_dict: dict
    ) -> None:
        base_res = validate_policy_dict(base_policy_dict)
        base_fp = base_res.fingerprint

        # 1. Edit regions
        d_reg = copy.deepcopy(base_policy_dict)
        d_reg["regions"] = ["DE", "AT"]
        assert validate_policy_dict(d_reg).fingerprint != base_fp

        # 2. Edit role aliases
        d_roles = copy.deepcopy(base_policy_dict)
        d_roles["role_aliases"]["Software Engineer"].append("Coder")
        assert validate_policy_dict(d_roles).fingerprint != base_fp

        # 3. Edit skill aliases
        d_skills = copy.deepcopy(base_policy_dict)
        d_skills["skill_aliases"]["Python"].append("CPython")
        assert validate_policy_dict(d_skills).fingerprint != base_fp

        # 4. Edit hard criteria operator
        d_op = copy.deepcopy(base_policy_dict)
        d_op["hard_criteria"][0]["expected_value"] = ["remote"]
        assert validate_policy_dict(d_op).fingerprint != base_fp

        # 5. Edit preference weight
        d_wt = copy.deepcopy(base_policy_dict)
        d_wt["preferences"][0]["weight"] = 0.5
        assert validate_policy_dict(d_wt).fingerprint != base_fp

        # 6. Edit exclusions
        d_ex = copy.deepcopy(base_policy_dict)
        d_ex["exclusions"].append("Crypto")
        assert validate_policy_dict(d_ex).fingerprint != base_fp

        # 7. Edit missing information behavior
        d_miss = copy.deepcopy(base_policy_dict)
        d_miss["missing_information_behavior"]["compensation"] = "fail"
        assert validate_policy_dict(d_miss).fingerprint != base_fp

        # 8. Edit min_score_threshold
        d_thresh = copy.deepcopy(base_policy_dict)
        d_thresh["relevance_configuration"]["min_score_threshold"] = 80.0
        assert validate_policy_dict(d_thresh).fingerprint != base_fp

        # 9. Edit broad keywords
        d_kw = copy.deepcopy(base_policy_dict)
        d_kw["relevance_configuration"]["broad_keywords"].append("Django")
        assert validate_policy_dict(d_kw).fingerprint != base_fp

        # 10. Edit context strategy (json -> rag)
        d_strat = copy.deepcopy(base_policy_dict)
        d_strat["primary_context_strategy"] = "rag"
        assert validate_policy_dict(d_strat).fingerprint != base_fp

    def test_round_trip_effective_policy_reloads_to_same_fingerprint(
        self, base_policy_dict: dict
    ) -> None:
        res1 = validate_policy_dict(base_policy_dict)
        assert res1.is_valid
        effective_dump = res1.effective_policy.policy.model_dump()

        res2 = validate_policy_dict(effective_dump)
        assert res2.is_valid
        assert res2.fingerprint == res1.fingerprint

