"""Compensation normalization and explicit unit enforcement (INGEST-02).

Preserves actual compensation facts without fabricating units or comparability:
- Parses Decimal bounds safely, preserving exact/range/lower-only/upper-only meanings.
- Rejects booleans, negative amounts, and reversed ranges (min > max).
- Normalizes unambiguous currencies (EUR, USD, GBP, CHF) and periods (hourly, monthly, yearly).
- Rejects ambiguous currency symbols (bare '$').
- Flags unsupported periods (weekly, daily) as unsupported_representation.
- Enforces that incomplete-unit compensation remains None (unknown) with warnings,
  preventing C06 JobCompensation from silently defaulting currency to EUR or period to yearly.
- Preserves gross/net and compensation provenance (employer, estimated, unknown).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from job_automation.contracts.enums import CompensationProvenance, SalaryPeriod
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.postings import JobCompensation

# Currency symbols and aliases
CURRENCY_MAP: dict[str, str] = {
    "eur": "EUR",
    "€": "EUR",
    "euro": "EUR",
    "gbp": "GBP",
    "£": "GBP",
    "chf": "CHF",
    "usd": "USD",
}

# Period keyword mappings
PERIOD_MAP: dict[str, SalaryPeriod] = {
    "/jahr": SalaryPeriod.YEARLY,
    "pro jahr": SalaryPeriod.YEARLY,
    "/year": SalaryPeriod.YEARLY,
    "per year": SalaryPeriod.YEARLY,
    "jährlich": SalaryPeriod.YEARLY,
    "yearly": SalaryPeriod.YEARLY,
    "annually": SalaryPeriod.YEARLY,
    "p.a.": SalaryPeriod.YEARLY,
    "per annum": SalaryPeriod.YEARLY,
    "/monat": SalaryPeriod.MONTHLY,
    "pro monat": SalaryPeriod.MONTHLY,
    "/month": SalaryPeriod.MONTHLY,
    "per month": SalaryPeriod.MONTHLY,
    "monatlich": SalaryPeriod.MONTHLY,
    "monthly": SalaryPeriod.MONTHLY,
    "/stunde": SalaryPeriod.HOURLY,
    "pro stunde": SalaryPeriod.HOURLY,
    "/hour": SalaryPeriod.HOURLY,
    "per hour": SalaryPeriod.HOURLY,
    "stündlich": SalaryPeriod.HOURLY,
    "hourly": SalaryPeriod.HOURLY,
}

UNSUPPORTED_PERIODS = frozenset(
    {
        "/woche",
        "pro woche",
        "/week",
        "per week",
        "wöchentlich",
        "weekly",
        "/tag",
        "pro tag",
        "/day",
        "per day",
        "täglich",
        "daily",
    }
)


def _parse_numeric_amount(num_str: str) -> Decimal | None:
    """Parse a German or English formatted number into a Decimal."""
    s = num_str.strip()
    if not s:
        return None

    # Handle German format: 60.000 or 4.500,50
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            # German: 4.500,50 -> 4500.50
            s = s.replace(".", "").replace(",", ".")
        else:
            # English: 4,500.50 -> 4500.50
            s = s.replace(",", "")
    elif "." in s:
        # Check if dot is thousands separator: e.g. 60.000 or 75.000
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and int(parts[0]) > 0:
            s = s.replace(".", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and int(parts[0]) > 0:
            s = s.replace(",", "")
        else:
            # German decimal: 25,50 -> 25.50
            s = s.replace(",", ".")

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def normalize_compensation(
    compensation_raw: Any,
) -> tuple[JobCompensation | None, list[ValidationIssue]]:
    """Normalize compensation into a JobCompensation model or structured issues.

    Returns:
        (compensation, issues)
    """
    if compensation_raw is None:
        return None, []

    # Explicitly reject boolean
    if isinstance(compensation_raw, bool):
        return None, [
            ValidationIssue(
                field_path="compensation",
                code="invalid_field_type",
                message="compensation must not be a boolean",
                severity="error",
            )
        ]

    issues: list[ValidationIssue] = []

    # 1. Structured dictionary input
    if isinstance(compensation_raw, dict):
        min_amt_raw = compensation_raw.get("min_amount")
        max_amt_raw = compensation_raw.get("max_amount")
        currency_raw = compensation_raw.get("currency")
        period_raw = compensation_raw.get("period")
        is_gross = compensation_raw.get("is_gross")
        prov_raw = compensation_raw.get("provenance")

        min_amt: Decimal | None = None
        max_amt: Decimal | None = None

        if min_amt_raw is not None:
            if isinstance(min_amt_raw, bool) or not isinstance(min_amt_raw, (int, float, str, Decimal)):
                return None, [
                    ValidationIssue(
                        field_path="compensation.min_amount",
                        code="invalid_field_type",
                        message="min_amount must be a numeric value",
                        severity="error",
                    )
                ]
            try:
                min_amt = Decimal(str(min_amt_raw))
            except InvalidOperation:
                return None, [
                    ValidationIssue(
                        field_path="compensation.min_amount",
                        code="invalid_value",
                        message=f"Invalid min_amount value '{min_amt_raw}'",
                        severity="error",
                    )
                ]
            if min_amt < 0:
                return None, [
                    ValidationIssue(
                        field_path="compensation.min_amount",
                        code="invalid_value",
                        message="min_amount cannot be negative",
                        severity="error",
                    )
                ]

        if max_amt_raw is not None:
            if isinstance(max_amt_raw, bool) or not isinstance(max_amt_raw, (int, float, str, Decimal)):
                return None, [
                    ValidationIssue(
                        field_path="compensation.max_amount",
                        code="invalid_field_type",
                        message="max_amount must be a numeric value",
                        severity="error",
                    )
                ]
            try:
                max_amt = Decimal(str(max_amt_raw))
            except InvalidOperation:
                return None, [
                    ValidationIssue(
                        field_path="compensation.max_amount",
                        code="invalid_value",
                        message=f"Invalid max_amount value '{max_amt_raw}'",
                        severity="error",
                    )
                ]
            if max_amt < 0:
                return None, [
                    ValidationIssue(
                        field_path="compensation.max_amount",
                        code="invalid_value",
                        message="max_amount cannot be negative",
                        severity="error",
                    )
                ]

        if min_amt is not None and max_amt is not None and min_amt > max_amt:
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="invalid_value",
                    message=f"min_amount ({min_amt}) cannot be greater than max_amount ({max_amt})",
                    severity="error",
                )
            ]

        # Currency validation
        if not currency_raw or not str(currency_raw).strip():
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="unsupported_representation",
                    message="Compensation missing explicit currency; cannot default to EUR",
                    severity="warning",
                )
            ]
        curr_str = str(currency_raw).strip().upper()
        if len(curr_str) != 3 or not curr_str.isalpha():
            return None, [
                ValidationIssue(
                    field_path="compensation.currency",
                    code="invalid_value",
                    message=f"Currency '{curr_str}' must be a 3-letter ISO-4217 code",
                    severity="error",
                )
            ]

        # Period validation
        if not period_raw:
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="unsupported_representation",
                    message="Compensation missing explicit period; cannot default to yearly",
                    severity="warning",
                )
            ]
        p_val = str(period_raw).strip().lower()
        if p_val in ("yearly", "year", "annual", "annually"):
            period = SalaryPeriod.YEARLY
        elif p_val in ("monthly", "month"):
            period = SalaryPeriod.MONTHLY
        elif p_val in ("hourly", "hour"):
            period = SalaryPeriod.HOURLY
        else:
            return None, [
                ValidationIssue(
                    field_path="compensation.period",
                    code="unsupported_representation",
                    message=f"Salary period '{p_val}' is not supported in SalaryPeriod enum",
                    severity="warning",
                )
            ]

        # Provenance
        provenance = CompensationProvenance.UNKNOWN
        if prov_raw:
            p_str = str(prov_raw).strip().lower()
            if p_str in ("employer", "employer_provided"):
                provenance = CompensationProvenance.EMPLOYER_PROVIDED
            elif p_str in ("estimated", "estimate"):
                provenance = CompensationProvenance.ESTIMATED

        return (
            JobCompensation(
                min_amount=min_amt,
                max_amount=max_amt,
                currency=curr_str,
                period=period,
                is_gross=is_gross if isinstance(is_gross, bool) else None,
                provenance=provenance,
            ),
            issues,
        )

    # 2. String representation input
    if isinstance(compensation_raw, str):
        comp_str = compensation_raw.strip()
        if not comp_str:
            return None, []

        comp_lower = comp_str.lower()

        # Check for bare '$' ambiguity
        if "$" in comp_str and "usd" not in comp_lower:
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="ambiguous_value",
                    message="Currency symbol '$' is ambiguous across USD, CAD, AUD; compensation remains unknown",
                    severity="warning",
                )
            ]

        # Resolve currency
        currency: str | None = None
        for key, curr in CURRENCY_MAP.items():
            if key in comp_lower:
                currency = curr
                break

        # Check for unsupported period (weekly, daily)
        if any(up in comp_lower for up in UNSUPPORTED_PERIODS):
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="unsupported_representation",
                    message="Weekly or daily compensation period is not supported in SalaryPeriod enum",
                    severity="warning",
                )
            ]

        # Resolve period
        period: SalaryPeriod | None = None
        for p_key, p_val in PERIOD_MAP.items():
            if p_key in comp_lower:
                period = p_val
                break

        # Resolve gross / net
        is_gross: bool | None = None
        if "brutto" in comp_lower or "gross" in comp_lower:
            is_gross = True
        elif "netto" in comp_lower or "net" in comp_lower:
            is_gross = False

        # Resolve provenance
        provenance = CompensationProvenance.UNKNOWN
        if "geschätzt" in comp_lower or "estimated" in comp_lower or "estimate" in comp_lower:
            provenance = CompensationProvenance.ESTIMATED
        elif "arbeitgeber" in comp_lower or "employer" in comp_lower:
            provenance = CompensationProvenance.EMPLOYER_PROVIDED

        # Extract numeric amounts
        # Look for patterns:
        # e.g. "60.000 - 75.000" or "75.000 – 85.000" or "ab 4.500" or "bis 80.000" or "25" or "70000"
        min_amount: Decimal | None = None
        max_amount: Decimal | None = None

        # Clean words that are not part of numbers
        # Find all number candidates (digits, dots, commas)
        number_candidates = re.findall(r"\b\d+(?:[.,]\d+)*\b", comp_str)

        if len(number_candidates) >= 2:
            min_amount = _parse_numeric_amount(number_candidates[0])
            max_amount = _parse_numeric_amount(number_candidates[1])
        elif len(number_candidates) == 1:
            amt = _parse_numeric_amount(number_candidates[0])
            if "ab " in comp_lower or "von " in comp_lower or "min " in comp_lower:
                min_amount = amt
            elif "bis " in comp_lower or "max " in comp_lower:
                max_amount = amt
            else:
                min_amount = amt
                max_amount = amt
        else:
            # No numbers found
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="unsupported_representation",
                    message=f"No numeric compensation bounds could be parsed from '{comp_str}'",
                    severity="warning",
                )
            ]

        # Validate range invariants
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="invalid_value",
                    message=f"Compensation min ({min_amount}) cannot exceed max ({max_amount})",
                    severity="error",
                )
            ]

        if (min_amount is not None and min_amount < 0) or (max_amount is not None and max_amount < 0):
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="invalid_value",
                    message="Compensation amounts cannot be negative",
                    severity="error",
                )
            ]

        # Enforce explicit units: currency and period must both be known
        if currency is None:
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="unsupported_representation",
                    message="Compensation missing explicit currency; cannot default to EUR",
                    severity="warning",
                )
            ]

        if period is None:
            return None, [
                ValidationIssue(
                    field_path="compensation",
                    code="unsupported_representation",
                    message="Compensation missing explicit period; cannot default to yearly",
                    severity="warning",
                )
            ]

        return (
            JobCompensation(
                min_amount=min_amount,
                max_amount=max_amount,
                currency=currency,
                period=period,
                is_gross=is_gross,
                provenance=provenance,
            ),
            issues,
        )

    # Invalid type
    return None, [
        ValidationIssue(
            field_path="compensation",
            code="invalid_field_type",
            message=f"compensation must be a string or object, got {type(compensation_raw).__name__}",
            severity="error",
        )
    ]

