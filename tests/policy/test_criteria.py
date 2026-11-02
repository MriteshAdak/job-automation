"""Tests for POLICY-01-S04 hard criteria, preferences, and relevance validation."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.policy import (
    HardCriterion,
    PreferenceRule,
    RelevanceConfig,
    SearchPolicy,
)
from job_automation.policy.criteria import validate_criteria_and_preferences


class TestPolicyCriteriaValidation:
    def test_valid_criteria_and_preferences(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            regions=["DE"],
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_wp",
                    name="Remote or hybrid",
                    field="workplace_type",
                    operator="in",
                    expected_value=["remote", "hybrid"],
                    on_missing="unknown",
                ),
                HardCriterion(
                    criterion_id="c_sal",
                    name="Minimum salary",
                    field="compensation.min_amount",
                    operator="gte",
                    expected_value={"amount": 65000, "currency": "EUR", "period": "yearly"},
                    on_missing="fail",
                ),
            ],
            preferences=[
                PreferenceRule(
                    rule_id="p_wp",
                    name="Prefer remote",
                    field="workplace_type",
                    weight=0.8,
                    preferred_values=["remote"],
                )
            ],
            exclusions=["Gambling", "Casino"],
            relevance_configuration=RelevanceConfig(
                score_scale="0-100",
                min_score_threshold=70.0,
                broad_keywords=["Python", "Cloud"],
                negative_keywords=["Unpaid"],
            ),
            primary_context_strategy=ContextStrategy.JSON,
        )
        issues = validate_criteria_and_preferences(policy)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_reject_duplicate_rule_ids_across_hard_and_soft(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="rule_100",
                    name="Hard rule",
                    field="workplace_type",
                    operator="equals",
                    expected_value="remote",
                )
            ],
            preferences=[
                PreferenceRule(
                    rule_id="rule_100",
                    name="Soft rule with same ID",
                    field="workplace_type",
                    weight=0.5,
                    preferred_values=["remote"],
                )
            ],
        )
        issues = validate_criteria_and_preferences(policy)
        assert any(i.code == "duplicate_rule_id" for i in issues)

    def test_reject_invalid_enum_values(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c1",
                    name="Invalid workplace type",
                    field="workplace_type",
                    operator="equals",
                    expected_value="metaverse",
                )
            ],
        )
        issues = validate_criteria_and_preferences(policy)
        assert any(i.code == "invalid_enum_value" for i in issues)

    def test_reject_bare_salary_number(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_sal",
                    name="Bare salary",
                    field="compensation.min_amount",
                    operator="gte",
                    expected_value=70000,
                )
            ],
        )
        issues = validate_criteria_and_preferences(policy)
        assert any(i.code == "ambiguous_salary_units" for i in issues)

    def test_reject_unsupported_operator_for_field(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="c_wp_op",
                    name="Cannot use gte on workplace type",
                    field="workplace_type",
                    operator="gte",
                    expected_value=2,
                )
            ],
        )
        issues = validate_criteria_and_preferences(policy)
        assert any(i.code == "unsupported_operator" for i in issues)

    def test_reject_regex_in_exclusions(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            exclusions=["^Regex.*Corp$"],
        )
        issues = validate_criteria_and_preferences(policy)
        assert any(i.code == "regex_exclusion_forbidden" for i in issues)

    def test_reject_unsupported_relevance_scale(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            relevance_configuration=RelevanceConfig(
                score_scale="1-5",  # Unsupported
            ),
        )
        issues = validate_criteria_and_preferences(policy)
        assert any(i.code == "unsupported_score_scale" for i in issues)

    def test_reject_out_of_bounds_score_threshold(self) -> None:
        policy = SearchPolicy(
            policy_version="v1",
            relevance_configuration=RelevanceConfig(
                score_scale="0-100",
                min_score_threshold=150.0,
            ),
        )
        issues = validate_criteria_and_preferences(policy)
        assert any(i.code == "invalid_score_threshold" for i in issues)

