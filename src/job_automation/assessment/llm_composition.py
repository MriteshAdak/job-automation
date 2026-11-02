"""Composition of complete C11 Assessment records with authoritative deterministic precedence (MATCH-02-S06).

Enforces:
1. Confirmed hard failures, eligibility failures, or exclusions ALWAYS produce REJECTED.
2. Missing-information policy rejections (on_missing='fail') produce REJECTED and stay distinct from confirmed skill gaps.
3. Unresolved required unknowns, unsupported extractions, or candidate eligibility unknowns produce REVIEW.
4. Model score cannot override confirmed failures or review conditions to ELIGIBLE.
5. All original deterministic rule outcomes are preserved without alteration.
"""

from __future__ import annotations

import uuid
from typing import Union

from job_automation.assessment.llm_records import (
    AssessmentProposal,
    AssessmentRequest,
    DeterministicDecisionTrace,
    FindingStatus,
    RequirementObligation,
    RequirementSet,
)
from job_automation.contracts.assessment import (
    Assessment,
    LLMAssessmentMetadata,
    RequirementFinding,
)
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    HardCriterionResult,
)
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.policy import SearchPolicy
from job_automation.policy.models import EffectivePolicy


def compose_llm_assessment(
    request: AssessmentRequest,
    requirement_set: RequirementSet,
    validated_findings: list[RequirementFinding],
    validation_issues: list[ValidationIssue],
    proposal: AssessmentProposal,
    llm_metadata: LLMAssessmentMetadata,
    input_fingerprint: str,
) -> Assessment:
    """Compose validated C11 Assessment record enforcing deterministic authority hierarchy."""
    baseline = request.deterministic_baseline
    trace = request.deterministic_trace

    # Preserve all original deterministic rule outcomes
    rule_outcomes = list(baseline.rule_outcomes)

    # 1. Aggregate gaps and unknowns
    identified_gaps: list[str] = list(baseline.identified_gaps)
    identified_unknowns: list[str] = list(baseline.identified_unknowns)

    has_required_gap = False
    has_required_unknown = False

    for f in validated_findings:
        desc_str = f"{f.requirement_id} ({f.obligation.value}): {f.requirement_text} - {f.reason}"
        if f.status == FindingStatus.GAP:
            identified_gaps.append(desc_str)
            if f.obligation == RequirementObligation.REQUIRED:
                has_required_gap = True
        elif f.status == FindingStatus.UNKNOWN:
            identified_unknowns.append(desc_str)
            if f.obligation == RequirementObligation.REQUIRED:
                has_required_unknown = True

    for issue in validation_issues:
        identified_unknowns.append(f"Validation: [{issue.code}] {issue.message}")

    # 2. Determine final disposition by strict precedence
    final_disposition: AssessmentDisposition

    # Precedence 1: Deterministic confirmed failure or exclusion
    if trace.has_confirmed_hard_failure():
        final_disposition = AssessmentDisposition.REJECTED
    # Precedence 2: Deterministic missing-information policy rejection (on_missing='fail')
    elif trace.has_missing_data_rejection():
        final_disposition = AssessmentDisposition.REJECTED
    # Precedence 3: Other baseline deterministic rejection
    elif baseline.final_disposition == AssessmentDisposition.REJECTED:
        final_disposition = AssessmentDisposition.REJECTED
    # Precedence 4: Confirmed model gap on a REQUIRED requirement
    elif has_required_gap:
        final_disposition = AssessmentDisposition.REJECTED
    # Precedence 5: Review conditions (deterministic unknowns, eligibility unknowns, or model required unknowns)
    elif trace.has_review_condition() or baseline.final_disposition == AssessmentDisposition.REVIEW or has_required_unknown:
        final_disposition = AssessmentDisposition.REVIEW
    # Precedence 6: Semantic validation warnings present
    elif any(iss.code in ("unsupported_requirement_extraction", "semantic_contradiction", "missing_requirement_coverage") for iss in validation_issues):
        final_disposition = AssessmentDisposition.REVIEW
    # Precedence 7: Relevance score threshold evaluation
    else:
        min_threshold = None
        if hasattr(request.policy, "relevance") and request.policy.relevance:
            min_threshold = getattr(request.policy.relevance, "min_score_threshold", None)
        elif hasattr(request.policy, "policy") and hasattr(request.policy.policy, "relevance") and request.policy.policy.relevance:
            min_threshold = getattr(request.policy.policy.relevance, "min_score_threshold", None)

        if min_threshold is not None:
            if proposal.relevance_score is None or proposal.relevance_score < min_threshold:
                final_disposition = AssessmentDisposition.REVIEW
            else:
                final_disposition = AssessmentDisposition.ELIGIBLE
        else:
            final_disposition = AssessmentDisposition.ELIGIBLE

    # 3. Determine relevance decision
    relevance_decision: AssessmentDisposition
    if final_disposition == AssessmentDisposition.REJECTED and not trace.has_rejection():
        relevance_decision = AssessmentDisposition.REJECTED
    elif final_disposition == AssessmentDisposition.REVIEW:
        relevance_decision = AssessmentDisposition.REVIEW
    elif final_disposition == AssessmentDisposition.ELIGIBLE:
        relevance_decision = AssessmentDisposition.ELIGIBLE
    else:
        relevance_decision = baseline.relevance_decision

    # 4. Construct concise summary reason
    summary_parts: list[str] = []
    if final_disposition == AssessmentDisposition.REJECTED:
        rejection_reasons = identified_gaps or [proposal.summary_reason]
        summary_parts.append(f"Rejected: {'; '.join(rejection_reasons[:3])}")
    elif final_disposition == AssessmentDisposition.REVIEW:
        review_reasons = identified_unknowns or [proposal.summary_reason]
        summary_parts.append(f"Review required: {'; '.join(review_reasons[:3])}")
    else:
        summary_parts.append(f"Eligible: {proposal.summary_reason}")

    summary_reason = "; ".join(summary_parts)

    policy_ver = (
        request.policy.policy.policy_version
        if isinstance(request.policy, EffectivePolicy)
        else request.policy.policy_version
    )

    # 5. Score scale handling
    relevance_score = proposal.relevance_score
    score_scale = proposal.score_scale if relevance_score is not None else None

    return Assessment(
        assessment_id=request.assessment_id,
        canonical_job_id=request.canonical_job_id,
        posting_revision=request.posting_revision,
        profile_version=request.profile.profile_version,
        policy_version=policy_ver,
        assessment_method=AssessmentMethod.LLM,
        rule_outcomes=rule_outcomes,
        requirement_findings=validated_findings,
        relevance_decision=relevance_decision,
        relevance_score=relevance_score,
        score_scale=score_scale,
        identified_gaps=identified_gaps,
        identified_unknowns=identified_unknowns,
        summary_reason=summary_reason,
        final_disposition=final_disposition,
        model_metadata=llm_metadata,
        validation_issues=validation_issues,
        assessment_input_fingerprint=input_fingerprint,
        deterministic_trace_ref=trace.compute_digest(),
    )

