"""Whole-prompt budget evaluation and admission accounting for CONTEXT-01."""

from __future__ import annotations

from job_automation.context.errors import ContextBudgetOverflowError, ContextValidationError
from job_automation.context.records import WholePromptMeasurement
from job_automation.contracts.context import BudgetReport


class BudgetEvaluator:
    """Evaluates prompt token demand against configured model window and reserves.

    Enforces admission rule:
        P + O + M <= L
    where:
        P = total input tokens (measured or estimated)
        O = output reserve
        M = safety allowance
        L = effective model context window limit
    """

    @staticmethod
    def evaluate(
        measurement: WholePromptMeasurement,
        context_limit: int,
        output_reserve: int,
        safety_allowance: int = 0,
    ) -> BudgetReport:
        """Evaluate whole-prompt admission and return comprehensive BudgetReport.

        Raises ContextBudgetOverflowError if demand exceeds window or candidate allowance <= 0.
        """
        if context_limit <= 0:
            raise ContextValidationError(
                f"context_limit must be a positive integer, got {context_limit}",
                field_path="context_limit",
            )
        if output_reserve < 0:
            raise ContextValidationError(
                f"output_reserve must be non-negative, got {output_reserve}",
                field_path="output_reserve",
            )
        if safety_allowance < 0:
            raise ContextValidationError(
                f"safety_allowance must be non-negative, got {safety_allowance}",
                field_path="safety_allowance",
            )

        P = measurement.total_input_tokens
        O = output_reserve
        M = safety_allowance
        L = context_limit

        fixed_overhead = (
            measurement.instruction_tokens
            + measurement.job_tokens
            + measurement.framing_tokens
            + O
            + M
        )
        candidate_allowance = L - fixed_overhead
        total_demand = P + O + M
        remaining_capacity = L - total_demand
        overflow = max(0, total_demand - L)

        if candidate_allowance <= 0:
            deficit = max(1, fixed_overhead - L)
            raise ContextBudgetOverflowError(
                f"Fixed prompt instructions, job text, and output reserve ({fixed_overhead} tokens) "
                f"leave no positive candidate context allowance within window {L}; complete context was not produced",
                field_path="context_budget",
                details={
                    "overflow": deficit,
                    "total_input_tokens": P,
                    "candidate_tokens": measurement.candidate_tokens,
                    "candidate_allowance": candidate_allowance,
                    "output_reserve": O,
                    "safety_allowance": M,
                    "effective_window": L,
                    "is_exact": measurement.is_exact,
                    "measurement_method": measurement.method,
                },
            )

        if total_demand > L:
            raise ContextBudgetOverflowError(
                f"Full JSON context exceeds configured window by {overflow} token{'s' if overflow != 1 else ''}; "
                f"complete context was not produced",
                field_path="context_budget",
                details={
                    "overflow": overflow,
                    "total_input_tokens": P,
                    "candidate_tokens": measurement.candidate_tokens,
                    "candidate_allowance": candidate_allowance,
                    "output_reserve": O,
                    "safety_allowance": M,
                    "effective_window": L,
                    "is_exact": measurement.is_exact,
                    "measurement_method": measurement.method,
                },
            )

        return BudgetReport(
            total_input_tokens=P,
            candidate_tokens=measurement.candidate_tokens,
            instruction_tokens=measurement.instruction_tokens,
            job_tokens=measurement.job_tokens,
            framing_tokens=measurement.framing_tokens,
            output_reserve=O,
            safety_allowance=M,
            effective_window=L,
            candidate_allowance=candidate_allowance,
            total_demand=total_demand,
            remaining_capacity=remaining_capacity,
            overflow=0,
            fits=True,
            measurement_method=measurement.method,
            measurement_version=measurement.version,
            is_exact=measurement.is_exact,
        )

