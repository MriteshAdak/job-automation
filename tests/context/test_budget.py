"""Tests for whole-prompt budget evaluation and admission accounting."""

from __future__ import annotations

import pytest

from job_automation.context.budget import BudgetEvaluator
from job_automation.context.errors import ContextBudgetOverflowError, ContextValidationError
from job_automation.context.records import WholePromptMeasurement


class TestBudgetEvaluation:
    def test_exact_budget_boundary_fits(self) -> None:
        """P=3000, O=900, M=100, L=4000 fits exactly with remaining_capacity=0."""
        measurement = WholePromptMeasurement(
            total_input_tokens=3000,
            candidate_tokens=1500,
            instruction_tokens=500,
            job_tokens=900,
            framing_tokens=100,
            is_exact=True,
            method="exact_tokenizer_v1",
            version="1.0",
        )

        report = BudgetEvaluator.evaluate(
            measurement=measurement,
            context_limit=4000,
            output_reserve=900,
            safety_allowance=100,
        )

        assert report.fits is True
        assert report.total_demand == 4000
        assert report.remaining_capacity == 0
        assert report.overflow == 0
        assert report.effective_window == 4000
        assert report.candidate_tokens == 1500
        # Fixed overhead: inst(500) + job(900) + framing(100) + O(900) + M(100) = 2500
        # Candidate allowance = 4000 - 2500 = 1500
        assert report.candidate_allowance == 1500

    def test_overflow_by_one_token_fails_visibly(self) -> None:
        """P=3001, O=900, M=100, L=4000 raises ContextBudgetOverflowError with overflow=1."""
        measurement = WholePromptMeasurement(
            total_input_tokens=3001,
            candidate_tokens=1501,
            instruction_tokens=500,
            job_tokens=900,
            framing_tokens=100,
            is_exact=True,
            method="exact_tokenizer_v1",
            version="1.0",
        )

        with pytest.raises(ContextBudgetOverflowError) as exc_info:
            BudgetEvaluator.evaluate(
                measurement=measurement,
                context_limit=4000,
                output_reserve=900,
                safety_allowance=100,
            )

        err = exc_info.value
        assert "exceeds configured window by 1 token" in err.message
        assert err.details["overflow"] == 1
        assert err.details["total_input_tokens"] == 3001
        assert err.details["effective_window"] == 4000
        assert err.details["output_reserve"] == 900
        assert err.details["safety_allowance"] == 100

    def test_fixed_overhead_exhausts_window_alone(self) -> None:
        """When instructions + job + reserve exceed L, zero candidate allowance is caught."""
        measurement = WholePromptMeasurement(
            total_input_tokens=4200,
            candidate_tokens=200,
            instruction_tokens=1000,
            job_tokens=2500,
            framing_tokens=500,
            is_exact=True,
            method="exact_tokenizer_v1",
            version="1.0",
        )

        with pytest.raises(ContextBudgetOverflowError, match="leave no positive candidate context allowance"):
            BudgetEvaluator.evaluate(
                measurement=measurement,
                context_limit=4000,
                output_reserve=600,
                safety_allowance=100,
            )

    def test_invalid_parameters_raise_validation_error(self) -> None:
        measurement = WholePromptMeasurement(
            total_input_tokens=1000,
            candidate_tokens=500,
            instruction_tokens=200,
            job_tokens=250,
            framing_tokens=50,
            is_exact=True,
            method="exact_tokenizer_v1",
            version="1.0",
        )

        # Non-positive context limit
        with pytest.raises(ContextValidationError, match="positive integer"):
            BudgetEvaluator.evaluate(measurement, context_limit=0, output_reserve=500)

        # Negative output reserve
        with pytest.raises(ContextValidationError, match="non-negative"):
            BudgetEvaluator.evaluate(measurement, context_limit=4000, output_reserve=-10)

        # Negative safety allowance
        with pytest.raises(ContextValidationError, match="non-negative"):
            BudgetEvaluator.evaluate(measurement, context_limit=4000, output_reserve=500, safety_allowance=-1)

