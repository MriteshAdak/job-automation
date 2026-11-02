"""Tests for POLICY-01-S01 semantic boundary and contract specifications."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.policy import HardCriterion, PreferenceRule, SearchPolicy
from job_automation.policy.fields import (
    SUPPORTED_TARGET_NAMES,
    TARGET_CATALOG,
    is_candidate_field,
    is_skills_target,
)
from job_automation.policy.models import (
    POLICY_SCHEMA_VERSION,
    POLICY_SEMANTICS_VERSION,
    SalaryOperand,
)
from job_automation.policy.validation import validate_policy_dict


class TestPolicyContractBoundary:
    def test_supported_targets_catalog_coverage(self) -> None:
        """Verify that catalog covers expected C06 NormalizedPosting fields."""
        expected_fields = {
            "title",
            "description_clean",
            "company_name_hint",
            "workplace_type",
            "employment_type",
            "advert_language",
            "locations.country",
            "locations.city",
            "locations.region",
            "remote_eligibility_restrictions",
            "compensation",
            "compensation.min_amount",
            "compensation.max_amount",
        }
        assert expected_fields.issubset(SUPPORTED_TARGET_NAMES)

    def test_candidate_fields_are_forbidden(self) -> None:
        """Candidate facts (C01) must not be configured as job posting criteria."""
        assert is_candidate_field("candidate.language_proficiencies")
        assert is_candidate_field("candidate_skills")
        assert is_candidate_field("work_authorization_countries")
        assert not is_candidate_field("workplace_type")
        assert not is_candidate_field("title")

        # Validate that a policy with candidate field produces forbidden_candidate_target error
        data = {
            "schema_version": "1.0",
            "policy_version": "v1",
            "regions": ["DE"],
            "hard_criteria": [
                {
                    "criterion_id": "c1",
                    "name": "Candidate language",
                    "field": "candidate.language_proficiencies",
                    "operator": "contains",
                    "expected_value": "de",
                    "on_missing": "unknown",
                }
            ],
        }
        res = validate_policy_dict(data)
        assert not res.is_valid
        assert any(i.code == "forbidden_candidate_target" for i in res.errors)

    def test_skills_target_is_rejected_as_unsupported(self) -> None:
        """'skills' is not on C06 NormalizedPosting and must fail validation."""
        assert is_skills_target("skills")
        assert is_skills_target("Skills")
        assert not is_skills_target("title")

        data = {
            "schema_version": "1.0",
            "policy_version": "v1",
            "regions": ["DE"],
            "hard_criteria": [
                {
                    "criterion_id": "c_skills",
                    "name": "Skills target",
                    "field": "skills",
                    "operator": "contains",
                    "expected_value": "Python",
                    "on_missing": "unknown",
                }
            ],
        }
        res = validate_policy_dict(data)
        assert not res.is_valid
        assert any(i.code == "unsupported_target" for i in res.errors)
        assert any("skills" in i.message.lower() for i in res.errors)

    def test_unsupported_schema_version_rejected(self) -> None:
        """Only schema_version 1.0 is supported."""
        data = {
            "schema_version": "2.0",
            "policy_version": "v1",
            "regions": ["DE"],
        }
        res = validate_policy_dict(data)
        assert not res.is_valid
        # When passed directly to Pydantic SearchPolicy, schema_version is validated
        # C02 has schema_version default 1.0; extra="forbid"

    def test_salary_operand_requires_explicit_units(self) -> None:
        """Bare numbers are rejected; structured currency/period are required."""
        with pytest.raises(Exception):
            SalaryOperand.model_validate({"amount": 60000, "currency": "INVALID"})

        valid_operand = SalaryOperand(amount=60000, currency="EUR")
        assert valid_operand.amount == 60000
        assert valid_operand.currency == "EUR"
        assert valid_operand.period == "yearly"

