"""Tests for allowlisted operators, multi-location, and enums (MATCH-01-S03)."""

from __future__ import annotations

import pytest

from job_automation.assessment.errors import AssessmentConfigurationError
from job_automation.assessment.models import FactualOutcome
from job_automation.assessment.operators import evaluate_field_operator
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.postings import StructuredLocation


class TestOperators:
    def test_text_scalar_operators(self, make_posting) -> None:
        posting = make_posting(title="Senior Python Backend Engineer")

        # equals
        res, reason, _, _ = evaluate_field_operator("title", "equals", "Senior Python Backend Engineer", posting)
        assert res == FactualOutcome.PASS

        res, reason, _, _ = evaluate_field_operator("title", "equals", "Frontend Developer", posting)
        assert res == FactualOutcome.FAIL

        # not_equals
        res, reason, _, _ = evaluate_field_operator("title", "not_equals", "Frontend Developer", posting)
        assert res == FactualOutcome.PASS

        # contains
        res, reason, _, span = evaluate_field_operator("title", "contains", "Python", posting)
        assert res == FactualOutcome.PASS
        assert span is not None

        # not_contains
        res, reason, _, _ = evaluate_field_operator("title", "not_contains", "Java", posting)
        assert res == FactualOutcome.PASS

        res, reason, _, _ = evaluate_field_operator("title", "not_contains", "Python", posting)
        assert res == FactualOutcome.FAIL

    def test_workplace_type_enum_operators(self, make_posting) -> None:
        remote_posting = make_posting(workplace_type=WorkplaceType.REMOTE)
        onsite_posting = make_posting(workplace_type=WorkplaceType.ONSITE)
        unknown_posting = make_posting(workplace_type=WorkplaceType.UNKNOWN)

        # Remote equals remote -> PASS
        res, _, _, _ = evaluate_field_operator("workplace_type", "equals", "remote", remote_posting)
        assert res == FactualOutcome.PASS

        # Onsite equals remote -> FAIL
        res, _, _, _ = evaluate_field_operator("workplace_type", "equals", "remote", onsite_posting)
        assert res == FactualOutcome.FAIL

        # Unknown workplace equals remote -> UNKNOWN (not proven failure)
        res, _, _, _ = evaluate_field_operator("workplace_type", "equals", "remote", unknown_posting)
        assert res == FactualOutcome.UNKNOWN

        # Unknown workplace not_equals remote -> UNKNOWN (not proven passing)
        res, _, _, _ = evaluate_field_operator("workplace_type", "not_equals", "remote", unknown_posting)
        assert res == FactualOutcome.UNKNOWN

        # in list
        res, _, _, _ = evaluate_field_operator("workplace_type", "in", ["remote", "hybrid"], remote_posting)
        assert res == FactualOutcome.PASS

    def test_multilocation_positive_existential_logic(self, make_posting) -> None:
        # Job has two locations: Munich (DE) and Paris (FR)
        posting = make_posting()
        posting = posting.model_copy(
            update={
                "locations": [
                    StructuredLocation(raw_text="Munich, Germany", country="DE", city="Munich"),
                    StructuredLocation(raw_text="Paris, France", country="FR", city="Paris"),
                ]
            }
        )

        # Looking for DE -> PASS because Munich is in DE
        res, _, snippet, _ = evaluate_field_operator("locations.country", "equals", "DE", posting)
        assert res == FactualOutcome.PASS
        assert "Munich" in snippet

        # Looking for US -> FAIL because both Munich and Paris are known and neither is US
        res, _, _, _ = evaluate_field_operator("locations.country", "equals", "US", posting)
        assert res == FactualOutcome.FAIL

        # Partial location: Paris (FR) and unstated country alternative
        partial_posting = posting.model_copy(
            update={
                "locations": [
                    StructuredLocation(raw_text="Paris, France", country="FR", city="Paris"),
                    StructuredLocation(raw_text="Springfield", country=None, city="Springfield"),
                ]
            }
        )
        # Looking for DE: Paris is FR, but Springfield has country=None -> UNKNOWN!
        res, _, _, _ = evaluate_field_operator("locations.country", "equals", "DE", partial_posting)
        assert res == FactualOutcome.UNKNOWN

        # Empty locations -> UNKNOWN
        empty_posting = posting.model_copy(update={"locations": []})
        res, _, _, _ = evaluate_field_operator("locations.country", "equals", "DE", empty_posting)
        assert res == FactualOutcome.UNKNOWN

    def test_multilocation_negative_universal_logic(self, make_posting) -> None:
        # Job has Munich (DE) and Paris (FR)
        posting = make_posting()
        posting = posting.model_copy(
            update={
                "locations": [
                    StructuredLocation(raw_text="Munich, Germany", country="DE", city="Munich"),
                    StructuredLocation(raw_text="Paris, France", country="FR", city="Paris"),
                ]
            }
        )

        # not_equals US -> PASS (none of the alternatives are US)
        res, _, _, _ = evaluate_field_operator("locations.country", "not_equals", "US", posting)
        assert res == FactualOutcome.PASS

        # not_equals FR -> FAIL (one of the alternatives is FR)
        res, _, _, _ = evaluate_field_operator("locations.country", "not_equals", "FR", posting)
        assert res == FactualOutcome.FAIL

    def test_remote_restrictions_operator(self, make_posting) -> None:
        posting = make_posting(remote_restrictions=["DE", "AT"])

        # contains DE -> PASS
        res, _, _, _ = evaluate_field_operator("remote_eligibility_restrictions", "contains", "DE", posting)
        assert res == FactualOutcome.PASS

        # contains US -> FAIL
        res, _, _, _ = evaluate_field_operator("remote_eligibility_restrictions", "contains", "US", posting)
        assert res == FactualOutcome.FAIL

        # empty restrictions -> UNKNOWN
        empty_posting = make_posting(remote_restrictions=[])
        res, _, _, _ = evaluate_field_operator("remote_eligibility_restrictions", "contains", "DE", empty_posting)
        assert res == FactualOutcome.UNKNOWN

    def test_unsupported_operator_raises(self, make_posting) -> None:
        posting = make_posting()
        with pytest.raises(AssessmentConfigurationError, match="Unsupported operator"):
            evaluate_field_operator("title", "invalid_op", "foo", posting)

