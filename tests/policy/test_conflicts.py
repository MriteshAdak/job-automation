"""Tests for POLICY-01-S05 bounded cross-policy conflict detection."""

from __future__ import annotations

from job_automation.contracts.policy import (
    HardCriterion,
    PreferenceRule,
    RelevanceConfig,
    SearchPolicy,
)
from job_automation.policy.conflicts import detect_policy_conflicts
from job_automation.policy.vocabulary import validate_vocabulary


class TestPolicyConflictDetection:
    def test_disjoint_mandatory_scalar_domain_conflict(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_remote",
                    name="Must be remote",
                    field="workplace_type",
                    operator="equals",
                    expected_value="remote",
                ),
                HardCriterion(
                    criterion_id="c_onsite",
                    name="Must be onsite",
                    field="workplace_type",
                    operator="equals",
                    expected_value="onsite",
                ),
            ],
        )
        vocab, _ = validate_vocabulary({}, {})
        issues = detect_policy_conflicts(policy, vocab)
        errors = [i for i in issues if i.code == "contradictory_hard_criteria"]
        assert len(errors) == 1
        assert "c_remote" in errors[0].message
        assert "c_onsite" in errors[0].message

    def test_disjoint_set_operators_conflict(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_set1",
                    name="Remote or hybrid",
                    field="workplace_type",
                    operator="in",
                    expected_value=["remote", "hybrid"],
                ),
                HardCriterion(
                    criterion_id="c_set2",
                    name="Onsite only",
                    field="workplace_type",
                    operator="in",
                    expected_value=["onsite"],
                ),
            ],
        )
        vocab, _ = validate_vocabulary({}, {})
        issues = detect_policy_conflicts(policy, vocab)
        errors = [i for i in issues if i.code == "contradictory_hard_criteria"]
        assert len(errors) == 1

    def test_inverted_salary_bounds_conflict(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_sal_min",
                    name="Min pay 90k",
                    field="compensation.min_amount",
                    operator="gte",
                    expected_value={"amount": 90000, "currency": "EUR", "period": "yearly"},
                ),
                HardCriterion(
                    criterion_id="c_sal_max",
                    name="Max ceiling 60k",
                    field="compensation.max_amount",
                    operator="lte",
                    expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
                ),
            ],
        )
        vocab, _ = validate_vocabulary({}, {})
        issues = detect_policy_conflicts(policy, vocab)
        errors = [i for i in issues if i.code == "inverted_numeric_bounds"]
        assert len(errors) == 1
        assert "c_sal_min" in errors[0].message
        assert "c_sal_max" in errors[0].message

    def test_hard_requirement_vs_exclusion_direct_and_alias(self) -> None:
        roles = {
            "Software Developer": ["Coder", "Programmer"]
        }
        vocab, _ = validate_vocabulary(roles, {})

        # Direct match with exclusion
        policy_direct = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_req_title",
                    name="Require Gambling in title",
                    field="title",
                    operator="contains",
                    expected_value="Gambling",
                )
            ],
            exclusions=["Gambling"],
        )
        issues_direct = detect_policy_conflicts(policy_direct, vocab)
        assert any(i.code == "exclusion_conflict" for i in issues_direct)

        # Match via alias: Coder resolves to Software Developer, which is excluded
        policy_alias = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_req_alias",
                    name="Require Coder in title",
                    field="title",
                    operator="contains",
                    expected_value="Coder",
                )
            ],
            exclusions=["Software Developer"],
        )
        issues_alias = detect_policy_conflicts(policy_alias, vocab)
        assert any(i.code == "exclusion_conflict" for i in issues_alias)

    def test_soft_preference_unreachable_generates_warning(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_remote_hard",
                    name="Hard remote",
                    field="workplace_type",
                    operator="equals",
                    expected_value="remote",
                )
            ],
            preferences=[
                PreferenceRule(
                    rule_id="p_onsite_soft",
                    name="Soft preference for onsite",
                    field="workplace_type",
                    weight=0.5,
                    preferred_values=["onsite"],
                )
            ],
        )
        vocab, _ = validate_vocabulary({}, {})
        issues = detect_policy_conflicts(policy, vocab)
        warnings = [i for i in issues if i.code == "unreachable_preference"]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"
        # Ensure no blocking errors were raised
        assert len([i for i in issues if i.severity == "error"]) == 0

    def test_contradictory_relevance_keywords(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            relevance_configuration=RelevanceConfig(
                broad_keywords=["Python", "Cloud"],
                negative_keywords=["Cloud", "Unpaid"],
            ),
        )
        vocab, _ = validate_vocabulary({}, {})
        issues = detect_policy_conflicts(policy, vocab)
        errors = [i for i in issues if i.code == "contradictory_relevance_keywords"]
        assert len(errors) == 1
        assert "Cloud" in errors[0].message

