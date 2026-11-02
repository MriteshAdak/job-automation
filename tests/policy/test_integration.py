"""Integration tests for POLICY-01 search policy lifecycle and downstream consumer contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_automation.contracts.policy import SearchPolicy
from job_automation.policy.service import PolicyService


class CapturingMatcherStub:
    """Consumer stub representing downstream MATCH-01 / RUN-01 boundary.
    
    Verifies that the consumer receives an effective SearchPolicy with its
    policy_version bound to the computed fingerprint, without evaluating jobs.
    """

    def __init__(self) -> None:
        self.received_policies: list[SearchPolicy] = []
        self.observed_versions: list[str] = []

    def accept_policy(self, effective_policy: SearchPolicy) -> str:
        self.received_policies.append(effective_policy)
        self.observed_versions.append(effective_policy.policy_version)
        return effective_policy.policy_version


class TestPolicyIntegration:
    @pytest.fixture
    def fixture_dir(self) -> Path:
        return Path("tests/fixtures/policy")

    def test_fixture_corpus_validation_matrix(self, fixture_dir: Path) -> None:
        """Verify expected validation outcomes for all synthetic fixtures in the catalog."""
        # 1. Valid technical policy
        res_tech = PolicyService.load_and_validate(fixture_dir / "valid_tech.json")
        assert res_tech.is_valid
        assert res_tech.fingerprint is not None
        assert len(res_tech.errors) == 0

        # 2. Valid office policy
        res_office = PolicyService.load_and_validate(fixture_dir / "valid_office.json")
        assert res_office.is_valid
        assert res_office.fingerprint is not None
        assert len(res_office.errors) == 0

        # 3. Duplicate key
        res_dup_key = PolicyService.load_and_validate(fixture_dir / "invalid_duplicate_key.json")
        assert not res_dup_key.is_valid
        assert any(i.code == "duplicate_json_key" for i in res_dup_key.issues)

        # 4. Duplicate rule ID
        res_dup_id = PolicyService.load_and_validate(fixture_dir / "invalid_duplicate_rule_id.json")
        assert not res_dup_id.is_valid
        assert any(i.code == "duplicate_rule_id" for i in res_dup_id.issues)

        # 5. Ambiguous alias
        res_ambig = PolicyService.load_and_validate(fixture_dir / "invalid_ambiguous_alias.json")
        assert not res_ambig.is_valid
        assert any(i.code == "ambiguous_alias" for i in res_ambig.issues)

        # 6. Alias chain
        res_chain = PolicyService.load_and_validate(fixture_dir / "invalid_alias_chain.json")
        assert not res_chain.is_valid
        assert any(i.code == "alias_chain" for i in res_chain.issues)

        # 7. Candidate field
        res_cand = PolicyService.load_and_validate(fixture_dir / "invalid_candidate_field.json")
        assert not res_cand.is_valid
        assert any(i.code == "forbidden_candidate_target" for i in res_cand.issues)

        # 8. Unsupported target (skills)
        res_skills = PolicyService.load_and_validate(fixture_dir / "invalid_unsupported_target.json")
        assert not res_skills.is_valid
        assert any(i.code == "unsupported_target" for i in res_skills.issues)

        # 9. Unsupported schema version
        res_schema = PolicyService.load_and_validate(fixture_dir / "invalid_unsupported_schema.json")
        assert not res_schema.is_valid
        assert any(i.code == "unsupported_schema_version" for i in res_schema.issues)

        # 10. Bare salary number
        res_bare_sal = PolicyService.load_and_validate(fixture_dir / "invalid_bare_salary.json")
        assert not res_bare_sal.is_valid
        assert any(i.code == "ambiguous_salary_units" for i in res_bare_sal.issues)

        # 11. Contradictory hard criteria
        res_contra = PolicyService.load_and_validate(fixture_dir / "invalid_contradictory_hard.json")
        assert not res_contra.is_valid
        assert any(i.code == "contradictory_hard_criteria" for i in res_contra.issues)

        # 12. Exclusion conflict
        res_excl = PolicyService.load_and_validate(fixture_dir / "invalid_exclusion_conflict.json")
        assert not res_excl.is_valid
        assert any(i.code == "exclusion_conflict" for i in res_excl.issues)

        # 13. Warning unreachable preference
        res_warn = PolicyService.load_and_validate(fixture_dir / "warning_unreachable_preference.json")
        assert res_warn.is_valid
        assert res_warn.fingerprint is not None
        assert len(res_warn.errors) == 0
        assert any(i.code == "unreachable_preference" and i.severity == "warning" for i in res_warn.issues)

    def test_downstream_consumer_receives_bound_effective_version(self, fixture_dir: Path) -> None:
        consumer = CapturingMatcherStub()

        res = PolicyService.load_and_validate(fixture_dir / "valid_tech.json")
        assert res.is_valid
        assert res.effective_policy is not None

        effective = res.effective_policy.policy
        ver = consumer.accept_policy(effective)

        # Bound version matches computed fingerprint
        assert ver == res.fingerprint
        assert ver.startswith("policy-v1:sha256:")
        assert consumer.observed_versions[0] == res.fingerprint

