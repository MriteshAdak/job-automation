"""Tests for compensation normalization and explicit unit enforcement (INGEST-02-S06)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from job_automation.contracts.enums import CompensationProvenance, SalaryPeriod
from job_automation.contracts.postings import JobCompensation
from job_automation.ingestion.normalization.compensation import normalize_compensation


def test_missing_salary_stays_unknown() -> None:
    """Missing or unstated salary remains None without generating warnings."""
    comp, issues = normalize_compensation(None)
    assert comp is None
    assert not issues


def test_normalize_german_range_with_explicit_units() -> None:
    """German formatted salary string with explicit units normalizes Decimal bounds."""
    raw = "60.000 - 75.000 EUR brutto/Jahr"
    comp, issues = normalize_compensation(raw)

    assert comp is not None
    assert comp.min_amount == Decimal("60000")
    assert comp.max_amount == Decimal("75000")
    assert comp.currency == "EUR"
    assert comp.period == SalaryPeriod.YEARLY
    assert comp.is_gross is True
    assert not any(iss.severity == "error" for iss in issues)


def test_normalize_hourly_rate() -> None:
    """Hourly compensation is normalized to SalaryPeriod.HOURLY without annualization."""
    raw = "25 EUR/Stunde"
    comp, issues = normalize_compensation(raw)

    assert comp is not None
    assert comp.min_amount == Decimal("25")
    assert comp.max_amount == Decimal("25")
    assert comp.currency == "EUR"
    assert comp.period == SalaryPeriod.HOURLY


def test_normalize_open_ended_bounds() -> None:
    """Lower-only ('ab') and upper-only ('bis') bounds normalize accurately."""
    comp_ab, _ = normalize_compensation("ab 4.500 EUR/Monat")
    assert comp_ab is not None
    assert comp_ab.min_amount == Decimal("4500")
    assert comp_ab.max_amount is None
    assert comp_ab.period == SalaryPeriod.MONTHLY

    comp_bis, _ = normalize_compensation("bis 80.000 EUR/Jahr")
    assert comp_bis is not None
    assert comp_bis.min_amount is None
    assert comp_bis.max_amount == Decimal("80000")
    assert comp_bis.period == SalaryPeriod.YEARLY


def test_explicit_zero_stays_zero() -> None:
    """Explicit 0 amount is preserved and not converted to null or absence."""
    comp_zero, _ = normalize_compensation("€0/hour")
    assert comp_zero is not None
    assert comp_zero.min_amount == Decimal("0")
    assert comp_zero.max_amount == Decimal("0")


def test_incomplete_units_stay_unknown_without_defaults() -> None:
    """Compensation with missing currency or missing period must NOT default to EUR/yearly.

    It must stay None (unknown) on NormalizedPosting with a warning issue.
    """
    # Missing period: 75.000 - 85.000 EUR
    comp_no_period, issues_no_period = normalize_compensation("75.000 - 85.000 EUR")
    assert comp_no_period is None
    assert any(iss.code == "unsupported_representation" for iss in issues_no_period)

    # Bare number without currency or period: 70000
    comp_bare, issues_bare = normalize_compensation("70000")
    assert comp_bare is None
    assert any(iss.code == "unsupported_representation" for iss in issues_bare)


def test_ambiguous_currency_symbol_stays_unknown() -> None:
    """Bare '$' is ambiguous across USD, CAD, AUD; stays unknown with warning."""
    comp_dollar, issues_dollar = normalize_compensation("$50,000 - $60,000 / year")
    assert comp_dollar is None
    assert any(iss.code == "ambiguous_value" for iss in issues_dollar)


def test_unsupported_period_stays_unknown() -> None:
    """Weekly salary is not supported by SalaryPeriod enum; stays unknown with warning."""
    comp_week, issues_week = normalize_compensation("600 EUR/woche")
    assert comp_week is None
    assert any(iss.code == "unsupported_representation" for iss in issues_week)


def test_inverted_range_produces_blocking_error() -> None:
    """Inverted compensation bounds (min > max) produce invalid_value error."""
    comp_rev, issues_rev = normalize_compensation("90000–70000 EUR/year")
    assert comp_rev is None
    assert any(iss.code == "invalid_value" and iss.severity == "error" for iss in issues_rev)


def test_negative_compensation_produces_blocking_error() -> None:
    """Negative compensation amounts produce invalid_value error."""
    comp_neg, issues_neg = normalize_compensation(
        {"min_amount": -500, "currency": "EUR", "period": "monthly"}
    )
    assert comp_neg is None
    assert any(iss.code == "invalid_value" and iss.severity == "error" for iss in issues_neg)


def test_boolean_compensation_rejected() -> None:
    """Booleans are rejected as invalid compensation field type."""
    comp_bool, issues_bool = normalize_compensation(True)
    assert comp_bool is None
    assert any(iss.code == "invalid_field_type" for iss in issues_bool)


def test_structured_dict_without_period_stays_unknown() -> None:
    """Structured dict without explicit period stays None rather than defaulting to yearly."""
    comp_no_period, issues = normalize_compensation(
        {"min_amount": 75000, "max_amount": 85000, "currency": "EUR"}
    )
    assert comp_no_period is None
    assert any(iss.code == "unsupported_representation" for iss in issues)

