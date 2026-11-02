"""Compensation evaluation comparing structured salary without invented units."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from job_automation.assessment.errors import AssessmentConfigurationError
from job_automation.assessment.evidence import build_job_evidence
from job_automation.assessment.models import FactualOutcome
from job_automation.contracts.enums import CompensationProvenance, SalaryPeriod
from job_automation.contracts.evidence import JobEvidenceReference
from job_automation.contracts.policy import HardCriterion
from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.models import SalaryOperand


def parse_and_validate_salary_operand(
    expected_value: Any,
    criterion_path: str = "hard_criteria",
) -> SalaryOperand:
    """Parse and strictly validate a compensation criterion operand.

    Requires explicit amount, currency, and period. Bare numbers or dictionaries
    missing explicit currency or period are rejected.
    """
    if isinstance(expected_value, SalaryOperand):
        return expected_value

    if not isinstance(expected_value, dict):
        raise AssessmentConfigurationError(
            f"Compensation criterion '{criterion_path}' requires a structured salary operand, "
            f"got {type(expected_value).__name__}"
        )

    # Require explicit currency and period keys in dict to prevent silent defaults
    if "currency" not in expected_value:
        raise AssessmentConfigurationError(
            f"Compensation criterion '{criterion_path}' is missing explicit 'currency' key"
        )
    if "period" not in expected_value:
        raise AssessmentConfigurationError(
            f"Compensation criterion '{criterion_path}' is missing explicit 'period' key"
        )
    if "amount" not in expected_value:
        raise AssessmentConfigurationError(
            f"Compensation criterion '{criterion_path}' is missing explicit 'amount' key"
        )

    raw_amt = expected_value["amount"]
    if isinstance(raw_amt, bool):
        raise AssessmentConfigurationError(
            f"Boolean value '{raw_amt}' is invalid for salary amount in '{criterion_path}'"
        )

    try:
        amt = Decimal(str(raw_amt))
        if not amt.is_finite() or amt <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise AssessmentConfigurationError(
            f"Salary amount '{raw_amt}' in '{criterion_path}' must be a strictly positive finite number"
        )

    try:
        return SalaryOperand.model_validate(expected_value)
    except Exception as exc:
        raise AssessmentConfigurationError(
            f"Invalid salary operand in '{criterion_path}': {exc}"
        ) from exc


def evaluate_compensation_criterion(
    criterion: HardCriterion,
    posting: NormalizedPosting,
    posting_revision: str,
) -> tuple[FactualOutcome, str, JobEvidenceReference | None]:
    """Evaluate a compensation hard criterion against a NormalizedPosting.

    Returns:
        (FactualOutcome, reason, JobEvidenceReference | None)
    """
    operand = parse_and_validate_salary_operand(
        criterion.expected_value,
        criterion_path=f"criterion['{criterion.criterion_id}']",
    )

    if posting.compensation is None:
        return (
            FactualOutcome.UNKNOWN,
            "Job posting does not state compensation",
            None,
        )

    comp = posting.compensation

    # Format structured compensation text for evidence
    comp_snippet = (
        f"{comp.min_amount if comp.min_amount is not None else '?'}"
        f" - {comp.max_amount if comp.max_amount is not None else '?'}"
        f" {comp.currency} {comp.period.value}"
    )

    # 1. Currency check: no implicit cross-currency conversion
    if comp.currency != operand.currency:
        evidence = build_job_evidence(
            posting,
            posting_revision,
            "compensation",
            quotation=comp_snippet,
        )
        return (
            FactualOutcome.UNKNOWN,
            f"Incompatible currency: posting offers '{comp.currency}', policy requires '{operand.currency}'",
            evidence,
        )

    # 2. Period check: no implicit annualization
    if comp.period != operand.period:
        evidence = build_job_evidence(
            posting,
            posting_revision,
            "compensation",
            quotation=comp_snippet,
        )
        return (
            FactualOutcome.UNKNOWN,
            f"Incompatible salary period: posting offers '{comp.period.value}', policy requires '{operand.period.value}'",
            evidence,
        )

    # 3. Provenance check
    if operand.provenance is not None and comp.provenance != operand.provenance:
        evidence = build_job_evidence(
            posting,
            posting_revision,
            "compensation",
            quotation=comp_snippet,
        )
        return (
            FactualOutcome.UNKNOWN,
            f"Compensation provenance mismatch: policy requires '{operand.provenance.value}', posting is '{comp.provenance.value}'",
            evidence,
        )

    # 4. Gross/net check
    if operand.is_gross is not None:
        if comp.is_gross is None:
            evidence = build_job_evidence(
                posting,
                posting_revision,
                "compensation",
                quotation=comp_snippet,
            )
            return (
                FactualOutcome.UNKNOWN,
                f"Tax basis unstated in posting: policy requires {'gross' if operand.is_gross else 'net'}",
                evidence,
            )
        if comp.is_gross != operand.is_gross:
            evidence = build_job_evidence(
                posting,
                posting_revision,
                "compensation",
                quotation=comp_snippet,
            )
            return (
                FactualOutcome.UNKNOWN,
                f"Tax basis mismatch: posting is {'gross' if comp.is_gross else 'net'}, policy requires {'gross' if operand.is_gross else 'net'}",
                evidence,
            )

    op = criterion.operator.lower().strip()
    target_amount = operand.amount

    # Scalar bound comparison (compensation.min_amount or compensation.max_amount)
    if criterion.field == "compensation.min_amount":
        if comp.min_amount is None:
            return (
                FactualOutcome.UNKNOWN,
                "Posting does not state a minimum compensation bound",
                build_job_evidence(posting, posting_revision, "compensation", quotation=comp_snippet),
            )
        bound = comp.min_amount
        return _compare_scalar_amount(bound, op, target_amount, comp_snippet, posting, posting_revision, "compensation.min_amount")

    if criterion.field == "compensation.max_amount":
        if comp.max_amount is None:
            return (
                FactualOutcome.UNKNOWN,
                "Posting does not state a maximum compensation bound",
                build_job_evidence(posting, posting_revision, "compensation", quotation=comp_snippet),
            )
        bound = comp.max_amount
        return _compare_scalar_amount(bound, op, target_amount, comp_snippet, posting, posting_revision, "compensation.max_amount")

    # Whole-compensation interval comparison
    c_min = comp.min_amount
    c_max = comp.max_amount

    if c_min is None and c_max is None:
        return (
            FactualOutcome.UNKNOWN,
            "Posting compensation does not provide numeric bounds",
            build_job_evidence(posting, posting_revision, "compensation", quotation=comp_snippet),
        )

    evidence = build_job_evidence(posting, posting_revision, "compensation", quotation=comp_snippet)

    if op in {"gte", ">="}:
        if c_min is not None and c_min >= target_amount:
            return FactualOutcome.PASS, f"Entire compensation range [{comp_snippet}] satisfies >= {target_amount}", evidence
        if c_max is not None and c_max < target_amount:
            return FactualOutcome.FAIL, f"Maximum offered pay {c_max} is below required minimum {target_amount}", evidence
        # Range straddles or incomplete bound
        return FactualOutcome.UNKNOWN, f"Offered compensation [{comp_snippet}] straddles or does not guarantee >= {target_amount}", evidence

    if op in {"gt", ">"}:
        if c_min is not None and c_min > target_amount:
            return FactualOutcome.PASS, f"Entire compensation range [{comp_snippet}] satisfies > {target_amount}", evidence
        if c_max is not None and c_max <= target_amount:
            return FactualOutcome.FAIL, f"Maximum offered pay {c_max} is not greater than {target_amount}", evidence
        return FactualOutcome.UNKNOWN, f"Offered compensation [{comp_snippet}] straddles or does not guarantee > {target_amount}", evidence

    if op in {"lte", "<="}:
        if c_max is not None and c_max <= target_amount:
            return FactualOutcome.PASS, f"Entire compensation range [{comp_snippet}] satisfies <= {target_amount}", evidence
        if c_min is not None and c_min > target_amount:
            return FactualOutcome.FAIL, f"Minimum offered pay {c_min} exceeds ceiling {target_amount}", evidence
        return FactualOutcome.UNKNOWN, f"Offered compensation [{comp_snippet}] straddles or does not guarantee <= {target_amount}", evidence

    if op in {"lt", "<"}:
        if c_max is not None and c_max < target_amount:
            return FactualOutcome.PASS, f"Entire compensation range [{comp_snippet}] satisfies < {target_amount}", evidence
        if c_min is not None and c_min >= target_amount:
            return FactualOutcome.FAIL, f"Minimum offered pay {c_min} is not less than {target_amount}", evidence
        return FactualOutcome.UNKNOWN, f"Offered compensation [{comp_snippet}] straddles or does not guarantee < {target_amount}", evidence

    if op in {"equals", "=="}:
        if c_min is not None and c_max is not None and c_min == c_max == target_amount:
            return FactualOutcome.PASS, f"Fixed compensation exactly equals {target_amount}", evidence
        if (c_min is not None and c_min > target_amount) or (c_max is not None and c_max < target_amount):
            return FactualOutcome.FAIL, f"Compensation range [{comp_snippet}] does not contain {target_amount}", evidence
        return FactualOutcome.UNKNOWN, f"Compensation range [{comp_snippet}] does not uniquely equal {target_amount}", evidence

    raise AssessmentConfigurationError(
        f"Unsupported operator '{op}' for compensation criterion"
    )


def _compare_scalar_amount(
    bound: Decimal,
    op: str,
    target_amount: Decimal,
    snippet: str,
    posting: NormalizedPosting,
    posting_revision: str,
    field_path: str,
) -> tuple[FactualOutcome, str, JobEvidenceReference | None]:
    evidence = build_job_evidence(posting, posting_revision, field_path, quotation=snippet)

    if op in {"gte", ">="}:
        if bound >= target_amount:
            return FactualOutcome.PASS, f"{field_path} ({bound}) satisfies >= {target_amount}", evidence
        return FactualOutcome.FAIL, f"{field_path} ({bound}) fails >= {target_amount}", evidence

    if op in {"gt", ">"}:
        if bound > target_amount:
            return FactualOutcome.PASS, f"{field_path} ({bound}) satisfies > {target_amount}", evidence
        return FactualOutcome.FAIL, f"{field_path} ({bound}) fails > {target_amount}", evidence

    if op in {"lte", "<="}:
        if bound <= target_amount:
            return FactualOutcome.PASS, f"{field_path} ({bound}) satisfies <= {target_amount}", evidence
        return FactualOutcome.FAIL, f"{field_path} ({bound}) fails <= {target_amount}", evidence

    if op in {"lt", "<"}:
        if bound < target_amount:
            return FactualOutcome.PASS, f"{field_path} ({bound}) satisfies < {target_amount}", evidence
        return FactualOutcome.FAIL, f"{field_path} ({bound}) fails < {target_amount}", evidence

    if op in {"equals", "=="}:
        if bound == target_amount:
            return FactualOutcome.PASS, f"{field_path} ({bound}) equals {target_amount}", evidence
        return FactualOutcome.FAIL, f"{field_path} ({bound}) does not equal {target_amount}", evidence

    raise AssessmentConfigurationError(
        f"Unsupported operator '{op}' for {field_path}"
    )

