"""Evaluation of hard criteria against job postings with honest missing-information actions."""

from __future__ import annotations

from typing import Union

from job_automation.assessment.compensation import evaluate_compensation_criterion
from job_automation.assessment.errors import AssessmentConfigurationError
from job_automation.assessment.evidence import build_job_evidence
from job_automation.assessment.models import (
    CriterionEvaluation,
    FactualOutcome,
    MissingActionSource,
)
from job_automation.assessment.operators import evaluate_field_operator
from job_automation.contracts.policy import HardCriterion, SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.fields import TARGET_CATALOG, is_candidate_field, is_skills_target
from job_automation.policy.models import EffectivePolicy


def resolve_criterion_missing_action(
    criterion: HardCriterion,
    policy: Union[EffectivePolicy, SearchPolicy],
) -> tuple[str, MissingActionSource]:
    """Resolve effective missing action ('pass', 'fail', 'unknown') and its source.

    Follows D03 missing-information precedence:
    1. Explicit rule-level on_missing in criterion
    2. Field default in missing_information_behavior
    3. Global default 'unknown'
    """
    if isinstance(policy, EffectivePolicy):
        eff = policy.effective_missing_actions.get(criterion.criterion_id)
        if eff is not None:
            source = MissingActionSource(eff.source)
            return eff.action, source

    # SearchPolicy resolution
    raw_policy = policy if isinstance(policy, SearchPolicy) else policy.policy
    if criterion.on_missing in {"pass", "fail"}:
        return criterion.on_missing, MissingActionSource.EXPLICIT_RULE

    field_default = raw_policy.missing_information_behavior.get(criterion.field)
    if field_default in {"pass", "fail", "unknown"}:
        return field_default, MissingActionSource.FIELD_DEFAULT

    return "unknown", MissingActionSource.GLOBAL_DEFAULT


def evaluate_hard_criterion(
    criterion: HardCriterion,
    posting: NormalizedPosting,
    posting_revision: str,
    policy: Union[EffectivePolicy, SearchPolicy],
) -> CriterionEvaluation:
    """Evaluate a single hard criterion against a posting."""
    field_name = criterion.field.strip()

    if is_candidate_field(field_name):
        raise AssessmentConfigurationError(
            f"Criterion '{criterion.criterion_id}' targets candidate field '{field_name}'. "
            "Search policy hard criteria target job posting fields only."
        )
    if is_skills_target(field_name):
        raise AssessmentConfigurationError(
            f"Criterion '{criterion.criterion_id}' targets raw 'skills' which is unsupported."
        )
    if field_name not in TARGET_CATALOG:
        raise AssessmentConfigurationError(
            f"Criterion '{criterion.criterion_id}' targets unsupported field '{field_name}'"
        )

    target_def = TARGET_CATALOG[field_name]
    action, source = resolve_criterion_missing_action(criterion, policy)

    # 1. Compensation evaluation
    if target_def.is_compensation:
        factual_result, reason, evidence = evaluate_compensation_criterion(
            criterion,
            posting,
            posting_revision,
        )
    # 2. General field evaluation
    else:
        factual_result, reason, snippet, span = evaluate_field_operator(
            field_name,
            criterion.operator,
            criterion.expected_value,
            posting,
        )
        evidence = build_job_evidence(
            posting,
            posting_revision,
            field_name,
            quotation=snippet,
            span=span,
        )

    # 3. Apply missing action if factual result is UNKNOWN
    is_waived = False
    is_policy_rejection = False

    if factual_result == FactualOutcome.UNKNOWN:
        if action == "pass":
            is_waived = True
            reason = f"[Policy Waived] {reason} (waived per on_missing='pass')"
        elif action == "fail":
            is_policy_rejection = True
            reason = f"[Policy Rejection] {reason} (rejected per on_missing='fail')"
        else:
            reason = f"[Unknown] {reason} (requires human review)"

    return CriterionEvaluation(
        criterion_id=criterion.criterion_id,
        criterion_name=criterion.name,
        target_field=field_name,
        factual_result=factual_result,
        effective_action=action,
        missing_action_source=source,
        is_waived=is_waived,
        is_policy_rejection=is_policy_rejection,
        job_evidence=evidence,
        reason=reason,
        missing_field=field_name if factual_result == FactualOutcome.UNKNOWN else None,
    )


def evaluate_all_hard_criteria(
    policy: Union[EffectivePolicy, SearchPolicy],
    posting: NormalizedPosting,
    posting_revision: str,
) -> list[CriterionEvaluation]:
    """Evaluate every configured hard criterion in order without short-circuiting."""
    raw_policy = policy if isinstance(policy, SearchPolicy) else policy.policy
    evaluations: list[CriterionEvaluation] = []
    for crit in raw_policy.hard_criteria:
        ev = evaluate_hard_criterion(crit, posting, posting_revision, policy)
        evaluations.append(ev)
    return evaluations

