"""Tests for compensation comparison and unit incompatibility (MATCH-01-S04)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from job_automation.assessment.compensation import (
    evaluate_compensation_criterion,
    parse_and_validate_salary_operand,
)
from job_automation.assessment.errors import AssessmentConfigurationError
from job_automation.assessment.models import FactualOutcome
from job_automation.contracts.enums import CompensationProvenance, SalaryPeriod
from job_automation.contracts.policy import HardCriterion
from job_automation.contracts.postings import JobCompensation


class TestCompensation:
    def test_missing_operand_units_rejected(self) -> None:
        # Missing currency
        with pytest.raises(AssessmentConfigurationError, match="missing explicit 'currency' key"):
            parse_and_validate_salary_operand({"amount": 60000, "period": "yearly"})

        # Missing period
        with pytest.raises(AssessmentConfigurationError, match="missing explicit 'period' key"):
            parse_and_validate_salary_operand({"amount": 60000, "currency": "EUR"})

        # Bare number
        with pytest.raises(AssessmentConfigurationError, match="requires a structured salary operand"):
            parse_and_validate_salary_operand(60000)

        # Non-positive amount
        with pytest.raises(AssessmentConfigurationError, match="strictly positive finite number"):
            parse_and_validate_salary_operand({"amount": -500, "currency": "EUR", "period": "yearly"})

    def test_incompatible_currencies_produce_unknown(self, make_posting) -> None:
        # Posting in USD, policy requires EUR
        comp = JobCompensation(
            min_amount=Decimal("70000"),
            max_amount=Decimal("80000"),
            currency="USD",
            period=SalaryPeriod.YEARLY,
        )
        posting = make_posting(compensation=comp)
        crit = HardCriterion(
            criterion_id="c_sal",
            name="Salary",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
        )

        res, reason, ev = evaluate_compensation_criterion(crit, posting, posting.raw_content_hash)
        assert res == FactualOutcome.UNKNOWN
        assert "Incompatible currency" in reason
        assert ev is not None
        assert "USD" in ev.quotation

    def test_incompatible_periods_produce_unknown(self, make_posting) -> None:
        # Posting in monthly pay, policy requires yearly (no implicit annualization)
        comp = JobCompensation(
            min_amount=Decimal("5000"),
            max_amount=Decimal("6000"),
            currency="EUR",
            period=SalaryPeriod.MONTHLY,
        )
        posting = make_posting(compensation=comp)
        crit = HardCriterion(
            criterion_id="c_sal",
            name="Salary",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
        )

        res, reason, ev = evaluate_compensation_criterion(crit, posting, posting.raw_content_hash)
        assert res == FactualOutcome.UNKNOWN
        assert "Incompatible salary period" in reason
        assert ev is not None

    def test_provenance_mismatch_produces_unknown(self, make_posting) -> None:
        # Posting has estimated compensation, policy requires employer-provided
        comp = JobCompensation(
            min_amount=Decimal("75000"),
            max_amount=Decimal("85000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
            provenance=CompensationProvenance.ESTIMATED,
        )
        posting = make_posting(compensation=comp)
        crit = HardCriterion(
            criterion_id="c_sal",
            name="Salary",
            field="compensation",
            operator="gte",
            expected_value={
                "amount": 60000,
                "currency": "EUR",
                "period": "yearly",
                "provenance": "employer_provided",
            },
        )

        res, reason, ev = evaluate_compensation_criterion(crit, posting, posting.raw_content_hash)
        assert res == FactualOutcome.UNKNOWN
        assert "Compensation provenance mismatch" in reason

    def test_interval_semantics(self, make_posting) -> None:
        crit = HardCriterion(
            criterion_id="c_sal",
            name="Salary",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
        )

        # 1. Entire range [65k, 75k] >= 60k -> PASS
        comp_pass = JobCompensation(
            min_amount=Decimal("65000"),
            max_amount=Decimal("75000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        p1 = make_posting(compensation=comp_pass)
        res1, reason1, _ = evaluate_compensation_criterion(crit, p1, p1.raw_content_hash)
        assert res1 == FactualOutcome.PASS
        assert "satisfies" in reason1

        # 2. Entire range [40k, 55k] < 60k -> FAIL
        comp_fail = JobCompensation(
            min_amount=Decimal("40000"),
            max_amount=Decimal("55000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        p2 = make_posting(compensation=comp_fail)
        res2, reason2, _ = evaluate_compensation_criterion(crit, p2, p2.raw_content_hash)
        assert res2 == FactualOutcome.FAIL
        assert "below required minimum" in reason2

        # 3. Straddling range [50k, 70k] vs 60k -> UNKNOWN
        comp_straddle = JobCompensation(
            min_amount=Decimal("50000"),
            max_amount=Decimal("70000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        p3 = make_posting(compensation=comp_straddle)
        res3, reason3, _ = evaluate_compensation_criterion(crit, p3, p3.raw_content_hash)
        assert res3 == FactualOutcome.UNKNOWN
        assert "straddles" in reason3

        # 4. Ceiling below threshold [?, 55k] -> FAIL
        comp_no_min = JobCompensation(
            min_amount=None,
            max_amount=Decimal("55000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        p4 = make_posting(compensation=comp_no_min)
        res4, _, _ = evaluate_compensation_criterion(crit, p4, p4.raw_content_hash)
        assert res4 == FactualOutcome.FAIL

        # 5. Floor meets threshold [65k, ?] -> PASS
        comp_no_max = JobCompensation(
            min_amount=Decimal("65000"),
            max_amount=None,
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        p5 = make_posting(compensation=comp_no_max)
        res5, _, _ = evaluate_compensation_criterion(crit, p5, p5.raw_content_hash)
        assert res5 == FactualOutcome.PASS

    def test_decimal_precision_preservation(self, make_posting) -> None:
        comp = JobCompensation(
            min_amount=Decimal("60000.00"),
            max_amount=Decimal("60000.00"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        p = make_posting(compensation=comp)
        crit = HardCriterion(
            criterion_id="c_sal",
            name="Salary",
            field="compensation",
            operator="equals",
            expected_value={"amount": "60000.00", "currency": "EUR", "period": "yearly"},
        )
        res, _, _ = evaluate_compensation_criterion(crit, p, p.raw_content_hash)
        assert res == FactualOutcome.PASS

