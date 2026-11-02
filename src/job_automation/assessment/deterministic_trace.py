"""Deterministic decision trace constructor for MATCH-01 outcomes."""

from __future__ import annotations

from typing import Any

from job_automation.assessment.eligibility import CandidateEligibilityCheckResult
from job_automation.assessment.llm_records import DeterministicDecisionTrace
from job_automation.assessment.models import (
    EVALUATOR_VERSION,
    CriterionEvaluation,
    ExclusionOutcome,
    FactualOutcome,
    PreferenceOutcome,
    RelevanceAssessmentResult,
)


def build_deterministic_trace(
    evaluations: list[CriterionEvaluation],
    eligibility_checks: list[CandidateEligibilityCheckResult],
    preferences: list[PreferenceOutcome],
    relevance: RelevanceAssessmentResult,
    exclusions: list[ExclusionOutcome],
    evaluator_version: str = EVALUATOR_VERSION,
) -> DeterministicDecisionTrace:
    """Build a typed DeterministicDecisionTrace capturing all MATCH-01 outcomes.

    Distinguishes:
    - Confirmed factual failures
    - Policy rejections due to missing information (on_missing='fail')
    - Factual unknowns requiring review
    - Explicit eligibility failures and unknowns
    - Exclusion rejections
    """
    confirmed_hard_failures: list[str] = []
    missing_data_rejections: list[str] = []
    factual_unknowns: list[str] = []

    for ev in evaluations:
        if ev.is_policy_rejection:
            missing_data_rejections.append(f"{ev.criterion_name}: {ev.reason}")
        elif ev.factual_result == FactualOutcome.FAIL and not ev.is_waived:
            confirmed_hard_failures.append(f"{ev.criterion_name}: {ev.reason}")
        elif ev.factual_result == FactualOutcome.UNKNOWN and not ev.is_waived:
            factual_unknowns.append(f"{ev.criterion_name}: {ev.reason}")

    eligibility_failures: list[str] = []
    eligibility_unknowns: list[str] = []
    checks_serialized: list[dict[str, Any]] = []

    for ec in eligibility_checks:
        checks_serialized.append(
            {
                "check_name": ec.check_name,
                "factual_result": str(ec.factual_result.value if hasattr(ec.factual_result, "value") else ec.factual_result),
                "reason": ec.reason,
            }
        )
        if ec.factual_result == FactualOutcome.FAIL:
            eligibility_failures.append(f"{ec.check_name}: {ec.reason}")
        elif ec.factual_result == FactualOutcome.UNKNOWN:
            eligibility_unknowns.append(f"{ec.check_name}: {ec.reason}")

    exclusion_rejections: list[str] = []
    for exc in exclusions:
        if exc.excluded and exc.reason:
            exclusion_rejections.append(f"Exclusion: {exc.reason}")

    return DeterministicDecisionTrace(
        evaluator_version=evaluator_version,
        evaluations=evaluations,
        eligibility_checks=checks_serialized,
        preferences=preferences,
        exclusions=exclusions,
        relevance=relevance,
        confirmed_hard_failures=confirmed_hard_failures,
        missing_data_rejections=missing_data_rejections,
        factual_unknowns=factual_unknowns,
        eligibility_failures=eligibility_failures,
        eligibility_unknowns=eligibility_unknowns,
        exclusion_rejections=exclusion_rejections,
    )

