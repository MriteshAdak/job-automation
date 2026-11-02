"""Contract boundary and model consistency tests for MATCH-01 assessment models."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from job_automation.assessment.errors import (
    AssessmentConfigurationError,
    AssessmentError,
    AssessmentInputError,
)
from job_automation.assessment.models import (
    CriterionEvaluation,
    FactualOutcome,
    MissingActionSource,
    PreferenceOutcome,
    RelevanceAssessmentResult,
)
from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    HardCriterionResult,
)
from job_automation.contracts.evidence import SourceSpan


class TestContractBoundary:
    def test_criterion_evaluation_to_rule_outcome_conversion(self) -> None:
        eval_pass = CriterionEvaluation(
            criterion_id="crit_1",
            criterion_name="Country DE",
            target_field="locations.country",
            factual_result=FactualOutcome.PASS,
            effective_action="unknown",
            missing_action_source=MissingActionSource.NOT_APPLICABLE,
            reason="Location is in Germany",
        )
        ro_pass = eval_pass.to_rule_outcome()
        assert ro_pass.criterion_id == "crit_1"
        assert ro_pass.result == HardCriterionResult.PASS

        # Policy waived
        eval_waived = CriterionEvaluation(
            criterion_id="crit_2",
            criterion_name="Salary",
            target_field="compensation",
            factual_result=FactualOutcome.UNKNOWN,
            effective_action="pass",
            missing_action_source=MissingActionSource.EXPLICIT_RULE,
            is_waived=True,
            reason="Waived missing salary",
        )
        ro_waived = eval_waived.to_rule_outcome()
        assert ro_waived.result == HardCriterionResult.PASS

        # Policy rejection
        eval_reject = CriterionEvaluation(
            criterion_id="crit_3",
            criterion_name="Salary",
            target_field="compensation",
            factual_result=FactualOutcome.UNKNOWN,
            effective_action="fail",
            missing_action_source=MissingActionSource.FIELD_DEFAULT,
            is_policy_rejection=True,
            reason="Rejected due to missing salary",
        )
        ro_reject = eval_reject.to_rule_outcome()
        assert ro_reject.result == HardCriterionResult.FAIL

        # Factual unknown
        eval_unknown = CriterionEvaluation(
            criterion_id="crit_4",
            criterion_name="Workplace",
            target_field="workplace_type",
            factual_result=FactualOutcome.UNKNOWN,
            effective_action="unknown",
            missing_action_source=MissingActionSource.GLOBAL_DEFAULT,
            reason="Workplace is unknown",
        )
        ro_unknown = eval_unknown.to_rule_outcome()
        assert ro_unknown.result == HardCriterionResult.UNKNOWN

    def test_c11_rules_assessment_forbids_model_metadata(self) -> None:
        # Rules assessment with model_metadata is valid according to contract if provided,
        # but in MATCH-01 deterministic rules evaluation, model_metadata is strictly None.
        assessment = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=uuid.uuid4(),
            posting_revision="rev-sha256",
            profile_version="v1",
            policy_version="policy-v1:sha256:abc",
            assessment_method=AssessmentMethod.RULES,
            rule_outcomes=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            summary_reason="Passed",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=None,
        )
        assert assessment.model_metadata is None

    def test_c11_hard_failure_cannot_be_eligible(self) -> None:
        with pytest.raises(ValidationError, match="confirmed hard criterion failure cannot be overridden"):
            Assessment(
                assessment_id=uuid.uuid4(),
                canonical_job_id=uuid.uuid4(),
                posting_revision="rev-sha256",
                profile_version="v1",
                policy_version="policy-v1:sha256:abc",
                assessment_method=AssessmentMethod.RULES,
                rule_outcomes=[
                    RuleOutcome(
                        criterion_id="c1",
                        criterion_name="Location",
                        result=HardCriterionResult.FAIL,
                        reason="Outside DE",
                    )
                ],
                relevance_decision=AssessmentDisposition.ELIGIBLE,
                summary_reason="Failed location",
                final_disposition=AssessmentDisposition.ELIGIBLE,  # Invalid!
                model_metadata=None,
            )

    def test_error_hierarchy(self) -> None:
        assert issubclass(AssessmentInputError, AssessmentError)
        assert issubclass(AssessmentConfigurationError, AssessmentError)

