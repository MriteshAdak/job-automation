"""Tests for hard rules evaluation and missing-action precedence (MATCH-01-S03)."""

from __future__ import annotations

import pytest

from job_automation.assessment.errors import AssessmentConfigurationError
from job_automation.assessment.hard_rules import evaluate_all_hard_criteria, evaluate_hard_criterion
from job_automation.assessment.models import FactualOutcome, MissingActionSource
from job_automation.contracts.enums import HardCriterionResult, WorkplaceType
from job_automation.contracts.policy import HardCriterion


class TestHardRules:
    def test_all_hard_criteria_evaluated_without_short_circuiting(
        self, make_posting, make_policy
    ) -> None:
        """Every configured hard criterion must be evaluated, even if an earlier one fails."""
        posting = make_posting(
            title="Junior Go Developer",
            country="FR",  # Location will fail
            workplace_type=WorkplaceType.ONSITE,  # Workplace will fail
        )
        policy = make_policy(
            hard_criteria=[
                HardCriterion(
                    criterion_id="crit_country",
                    name="Country Check",
                    field="locations.country",
                    operator="equals",
                    expected_value="DE",
                ),
                HardCriterion(
                    criterion_id="crit_workplace",
                    name="Workplace Remote",
                    field="workplace_type",
                    operator="equals",
                    expected_value="remote",
                ),
                HardCriterion(
                    criterion_id="crit_title",
                    name="Title Check",
                    field="title",
                    operator="contains",
                    expected_value="Go",
                ),
            ]
        )

        evaluations = evaluate_all_hard_criteria(policy, posting, posting.raw_content_hash)
        assert len(evaluations) == 3

        ro1 = evaluations[0].to_rule_outcome()
        assert ro1.criterion_id == "crit_country"
        assert ro1.result == HardCriterionResult.FAIL

        ro2 = evaluations[1].to_rule_outcome()
        assert ro2.criterion_id == "crit_workplace"
        assert ro2.result == HardCriterionResult.FAIL

        ro3 = evaluations[2].to_rule_outcome()
        assert ro3.criterion_id == "crit_title"
        assert ro3.result == HardCriterionResult.PASS

    def test_missing_action_precedence_and_waiving(self, make_posting, make_policy) -> None:
        # Posting has compensation None (missing salary)
        posting = make_posting(compensation=None)

        # 1. on_missing='pass' -> gate waived
        crit_waived = HardCriterion(
            criterion_id="c_sal_waived",
            name="Salary Check",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
            on_missing="pass",
        )
        policy_waived = make_policy(hard_criteria=[crit_waived])
        ev1 = evaluate_hard_criterion(crit_waived, posting, posting.raw_content_hash, policy_waived)
        assert ev1.factual_result == FactualOutcome.UNKNOWN
        assert ev1.is_waived is True
        assert ev1.is_policy_rejection is False
        assert ev1.to_rule_outcome().result == HardCriterionResult.PASS
        assert "[Policy Waived]" in ev1.reason

        # 2. on_missing='fail' -> policy rejection
        crit_fail = HardCriterion(
            criterion_id="c_sal_fail",
            name="Salary Check",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
            on_missing="fail",
        )
        policy_fail = make_policy(hard_criteria=[crit_fail])
        ev2 = evaluate_hard_criterion(crit_fail, posting, posting.raw_content_hash, policy_fail)
        assert ev2.factual_result == FactualOutcome.UNKNOWN
        assert ev2.is_waived is False
        assert ev2.is_policy_rejection is True
        assert ev2.to_rule_outcome().result == HardCriterionResult.FAIL
        assert "[Policy Rejection]" in ev2.reason

        # 3. on_missing='unknown' -> review
        crit_unk = HardCriterion(
            criterion_id="c_sal_unk",
            name="Salary Check",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
            on_missing="unknown",
        )
        policy_unk = make_policy(hard_criteria=[crit_unk])
        ev3 = evaluate_hard_criterion(crit_unk, posting, posting.raw_content_hash, policy_unk)
        assert ev3.factual_result == FactualOutcome.UNKNOWN
        assert ev3.is_waived is False
        assert ev3.is_policy_rejection is False
        assert ev3.to_rule_outcome().result == HardCriterionResult.UNKNOWN
        assert "[Unknown]" in ev3.reason

    def test_forbidden_candidate_target_raises_configuration_error(
        self, make_posting, make_policy
    ) -> None:
        posting = make_posting()
        crit = HardCriterion(
            criterion_id="c_cand",
            name="Candidate Target",
            field="candidate.work_authorization",
            operator="equals",
            expected_value="DE",
        )
        policy = make_policy(hard_criteria=[crit])
        with pytest.raises(AssessmentConfigurationError, match="targets candidate field"):
            evaluate_hard_criterion(crit, posting, posting.raw_content_hash, policy)

