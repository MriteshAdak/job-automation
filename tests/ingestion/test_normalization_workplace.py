"""Tests for workplace type, remote restrictions, and employment type normalization (INGEST-02-S05)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import EmploymentType, WorkplaceType
from job_automation.ingestion.normalization.workplace import (
    normalize_employment_type,
    normalize_workplace,
)


def test_normalize_workplace_aliases() -> None:
    """Workplace string aliases map to correct WorkplaceType enum members."""
    wp_onsite, _, _ = normalize_workplace("vor Ort")
    assert wp_onsite == WorkplaceType.ONSITE

    wp_hybrid, _, _ = normalize_workplace("hybrid (remote/onsite)")
    assert wp_hybrid == WorkplaceType.HYBRID

    wp_remote, _, _ = normalize_workplace("vollständig remote")
    assert wp_remote == WorkplaceType.REMOTE


def test_boolean_remote_true_and_false() -> None:
    """Boolean remote=True maps to REMOTE; remote=False stays UNKNOWN with warning."""
    wp_true, restr_true, issues_true = normalize_workplace(True)
    assert wp_true == WorkplaceType.REMOTE
    assert restr_true == []
    assert not issues_true

    wp_false, restr_false, issues_false = normalize_workplace(False)
    assert wp_false == WorkplaceType.UNKNOWN
    assert restr_false == []
    assert any(iss.code == "ambiguous_value" for iss in issues_false)


def test_remote_does_not_imply_worldwide_eligibility() -> None:
    """Remote workplace without stated restrictions leaves restrictions unknown/empty.

    Crucially: remote does NOT fabricate or imply worldwide eligibility.
    """
    wp, restrictions, issues = normalize_workplace(True, restrictions_raw=None)
    assert wp == WorkplaceType.REMOTE
    assert restrictions == []


def test_explicit_remote_restrictions() -> None:
    """Explicit remote geographic restrictions are normalized into country/region codes."""
    # Germany
    _, restr_de, _ = normalize_workplace("remote", restrictions_raw=["Deutschland"])
    assert restr_de == ["DE"]

    # EU
    _, restr_eu, _ = normalize_workplace("remote", restrictions_raw=["EU"])
    assert restr_eu == ["EU"]

    # Explicit worldwide/unrestricted produces empty restrictions set
    _, restr_ww, _ = normalize_workplace("remote", restrictions_raw=["worldwide"])
    assert restr_ww == []


def test_conflicting_workplace_assertions() -> None:
    """Conflicting onsite and remote indications without hybrid resolution stay UNKNOWN."""
    wp_conflict, _, issues_conflict = normalize_workplace("in-office and remote simultaneously")
    assert wp_conflict == WorkplaceType.UNKNOWN
    assert any(iss.code == "conflicting_values" for iss in issues_conflict)


def test_normalize_employment_type_aliases() -> None:
    """Single employment labels map to expected EmploymentType members."""
    emp_ft, _ = normalize_employment_type("Vollzeit")
    assert emp_ft == EmploymentType.FULL_TIME

    emp_pt, _ = normalize_employment_type("Teilzeit")
    assert emp_pt == EmploymentType.PART_TIME

    emp_contract, _ = normalize_employment_type("Freie Mitarbeit")
    assert emp_contract == EmploymentType.CONTRACT

    emp_intern, _ = normalize_employment_type("Werkstudent")
    assert emp_intern == EmploymentType.INTERNSHIP


def test_employment_type_list_equivalent_labels_collapse() -> None:
    """Equivalent labels in list (Vollzeit, Full-time) collapse into single enum."""
    emp_collapsed, issues = normalize_employment_type(["Vollzeit", "Full-time"])
    assert emp_collapsed == EmploymentType.FULL_TIME
    assert not issues


def test_employment_type_list_conflicting_labels() -> None:
    """Incompatible simultaneous labels (Vollzeit, Teilzeit) stay UNKNOWN with warning."""
    emp_incompatible, issues = normalize_employment_type(["Vollzeit", "Teilzeit"])
    assert emp_incompatible == EmploymentType.UNKNOWN
    assert any(iss.code == "conflicting_values" for iss in issues)


def test_invalid_employment_type_rejected() -> None:
    """Boolean employment type is rejected with invalid_field_type."""
    emp_bad, issues_bad = normalize_employment_type(True)
    assert emp_bad == EmploymentType.UNKNOWN
    assert any(iss.code == "invalid_field_type" for iss in issues_bad)

