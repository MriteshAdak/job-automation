"""Tests for POLICY-01-S04 missing-information precedence and resolution."""

from __future__ import annotations

from job_automation.contracts.policy import HardCriterion
from job_automation.policy.missing import resolve_effective_missing_actions


class TestMissingInformationPrecedence:
    def test_d03_precedence_matrix(self) -> None:
        """Verify D03 precedence: explicit rule > field default > global default unknown."""
        crits = [
            # 1. Explicit rule-level 'fail' overrides field default 'unknown'
            HardCriterion(
                criterion_id="crit_1",
                name="Rule with explicit fail",
                field="compensation.min_amount",
                operator="gte",
                expected_value={"amount": 50000, "currency": "EUR", "period": "yearly"},
                on_missing="fail",
            ),
            # 2. Explicit rule-level 'unknown' overrides field default 'pass'
            HardCriterion(
                criterion_id="crit_2",
                name="Rule with explicit unknown",
                field="workplace_type",
                operator="equals",
                expected_value="remote",
                on_missing="unknown",
            ),
            # 3. Omitted rule-level on_missing inherits field default 'pass'
            HardCriterion(
                criterion_id="crit_3",
                name="Rule omitting on_missing with field default",
                field="employment_type",
                operator="equals",
                expected_value="full_time",
                # on_missing defaults to 'unknown' on model, but explicit_on_missing flags it as False
            ),
            # 4. Omitted rule-level on_missing without field default resolves to global 'unknown'
            HardCriterion(
                criterion_id="crit_4",
                name="Rule omitting on_missing without field default",
                field="advert_language",
                operator="equals",
                expected_value="de",
            ),
        ]

        missing_behavior = {
            "compensation.min_amount": "unknown",
            "workplace_type": "pass",
            "employment_type": "pass",
        }

        explicit_flags = {
            "crit_1": True,   # Explicitly supplied in JSON
            "crit_2": True,   # Explicitly supplied in JSON
            "crit_3": False,  # Omitted from JSON
            "crit_4": False,  # Omitted from JSON
        }

        actions, issues = resolve_effective_missing_actions(crits, missing_behavior, explicit_flags)
        assert len([i for i in issues if i.severity == "error"]) == 0

        # Verify crit_1
        assert actions["crit_1"].action == "fail"
        assert actions["crit_1"].source == "explicit_rule"

        # Verify crit_2
        assert actions["crit_2"].action == "unknown"
        assert actions["crit_2"].source == "explicit_rule"

        # Verify crit_3
        assert actions["crit_3"].action == "pass"
        assert actions["crit_3"].source == "field_default"

        # Verify crit_4
        assert actions["crit_4"].action == "unknown"
        assert actions["crit_4"].source == "global_default"

    def test_unknown_field_in_missing_behavior_warns(self) -> None:
        crits = [
            HardCriterion(
                criterion_id="c1",
                name="Rule 1",
                field="workplace_type",
                operator="equals",
                expected_value="remote",
            )
        ]
        missing_behavior = {
            "completely_unknown_target": "unknown",
        }
        actions, issues = resolve_effective_missing_actions(crits, missing_behavior, {})
        assert any(i.code == "unknown_missing_field" and i.severity == "warning" for i in issues)

