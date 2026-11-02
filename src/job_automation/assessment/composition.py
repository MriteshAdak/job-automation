"""Composition of complete C11 Assessment records with strict precedence rules."""

from __future__ import annotations

from job_automation.assessment.eligibility import CandidateEligibilityCheckResult
from job_automation.assessment.models import (
    AssessmentInput,
    CriterionEvaluation,
    ExclusionOutcome,
    FactualOutcome,
    PreferenceOutcome,
    RelevanceAssessmentResult,
)
from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    HardCriterionResult,
)
from job_automation.policy.models import EffectivePolicy


def compose_assessment(
    assessment_input: AssessmentInput,
    evaluations: list[CriterionEvaluation],
    eligibility_checks: list[CandidateEligibilityCheckResult],
    preferences: list[PreferenceOutcome],
    relevance: RelevanceAssessmentResult,
    exclusions: list[ExclusionOutcome],
) -> Assessment:
    """Compose a complete, immutable C11 Assessment record.

    Enforces deterministic precedence:
    1. Confirmed hard rule failure, candidate eligibility failure, or exclusion -> REJECTED
    2. Missing information policy rejection (on_missing='fail') -> REJECTED
    3. Unresolved required facts (UNKNOWN), candidate eligibility unknowns, or inconclusive relevance -> REVIEW
    4. All hard rules passed/waived, no exclusions, relevance satisfied -> ELIGIBLE
    """
    rule_outcomes = [ev.to_rule_outcome() for ev in evaluations]

    identified_gaps: list[str] = []
    identified_unknowns: list[str] = []

    # 1. Inspect hard rule outcomes
    has_hard_fail = False
    has_hard_unknown = False

    for ev in evaluations:
        ro = ev.to_rule_outcome()
        if ro.result == HardCriterionResult.FAIL:
            has_hard_fail = True
            identified_gaps.append(f"{ev.criterion_name}: {ev.reason}")
        elif ro.result == HardCriterionResult.UNKNOWN:
            has_hard_unknown = True
            identified_unknowns.append(f"{ev.criterion_name}: {ev.reason}")

    # 2. Inspect candidate eligibility checks
    has_eligibility_fail = False
    has_eligibility_unknown = False

    for ec in eligibility_checks:
        if ec.factual_result == FactualOutcome.FAIL:
            has_eligibility_fail = True
            identified_gaps.append(f"{ec.check_name}: {ec.reason}")
        elif ec.factual_result == FactualOutcome.UNKNOWN:
            has_eligibility_unknown = True
            identified_unknowns.append(f"{ec.check_name}: {ec.reason}")

    # 3. Inspect exclusions
    has_exclusion = any(exc.excluded for exc in exclusions)
    if has_exclusion:
        for exc in exclusions:
            if exc.excluded and exc.reason:
                identified_gaps.append(f"Exclusion: {exc.reason}")

    # 4. Determine final disposition
    final_disposition: AssessmentDisposition

    if has_hard_fail or has_eligibility_fail or has_exclusion:
        final_disposition = AssessmentDisposition.REJECTED
    elif relevance.decision == AssessmentDisposition.REJECTED:
        final_disposition = AssessmentDisposition.REJECTED
    elif has_hard_unknown or has_eligibility_unknown or relevance.decision == AssessmentDisposition.REVIEW:
        final_disposition = AssessmentDisposition.REVIEW
    else:
        final_disposition = AssessmentDisposition.ELIGIBLE

    # 5. Build concise summary reason
    summary_parts: list[str] = []
    if final_disposition == AssessmentDisposition.REJECTED:
        rejection_reasons = identified_gaps or [relevance.reason]
        summary_parts.append(f"Rejected: {'; '.join(rejection_reasons[:3])}")
    elif final_disposition == AssessmentDisposition.REVIEW:
        review_reasons = identified_unknowns or [relevance.reason]
        summary_parts.append(f"Review required: {'; '.join(review_reasons[:3])}")
    else:
        matched_prefs = [p.name for p in preferences if p.matched]
        summary_parts.append("Eligible: all hard criteria satisfied")
        if relevance.broad_keyword_hits:
            summary_parts.append(f"matched keywords: {', '.join(relevance.broad_keyword_hits[:3])}")
        if matched_prefs:
            summary_parts.append(f"matched preferences: {', '.join(matched_prefs[:2])}")

    summary_reason = "; ".join(summary_parts)

    policy_ver = (
        assessment_input.policy.policy.policy_version
        if isinstance(assessment_input.policy, EffectivePolicy)
        else assessment_input.policy.policy_version
    )

    return Assessment(
        assessment_id=assessment_input.execution_id,
        canonical_job_id=assessment_input.canonical_job_id,
        posting_revision=assessment_input.posting_revision,
        profile_version=assessment_input.profile_version,
        policy_version=policy_ver,
        assessment_method=AssessmentMethod.RULES,
        rule_outcomes=rule_outcomes,
        relevance_decision=relevance.decision,
        relevance_score=None,  # Null for deterministic rules-only assessment
        score_scale=None,
        identified_gaps=identified_gaps,
        identified_unknowns=identified_unknowns,
        summary_reason=summary_reason,
        final_disposition=final_disposition,
        model_metadata=None,  # Null for deterministic rules-only assessment
    )

