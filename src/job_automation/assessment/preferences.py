"""Evaluation of soft preference rules for ranking and informative feedback."""

from __future__ import annotations

from typing import Union

from job_automation.assessment.evidence import build_job_evidence
from job_automation.assessment.fields import get_posting_field_value
from job_automation.assessment.literal_matching import contains_literal_phrase, find_literal_matches
from job_automation.assessment.models import PreferenceOutcome
from job_automation.contracts.policy import PreferenceRule, SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.models import EffectivePolicy
from job_automation.policy.vocabulary import normalize_lookup


def evaluate_preference_rule(
    preference: PreferenceRule,
    posting: NormalizedPosting,
    posting_revision: str,
) -> PreferenceOutcome:
    """Evaluate a single soft preference rule.

    Preferences provide positive ranking signals and never cause job rejection.
    """
    field_name = preference.field.strip()
    val, is_present = get_posting_field_value(posting, field_name)

    if not is_present or val is None:
        return PreferenceOutcome(
            rule_id=preference.rule_id,
            name=preference.name,
            field=field_name,
            weight=preference.weight,
            matched=False,
            is_unknown=True,
            reason=f"Target field '{field_name}' is not specified in posting",
        )

    # Multi-location preference check
    if field_name.startswith("locations."):
        attr = field_name.split(".", 1)[1]
        loc_values = [getattr(loc, attr, None) for loc in posting.locations if getattr(loc, attr, None)]
        preferred_set = {normalize_lookup(pv) for pv in preference.preferred_values}
        for lv in loc_values:
            if normalize_lookup(lv) in preferred_set:
                return PreferenceOutcome(
                    rule_id=preference.rule_id,
                    name=preference.name,
                    field=field_name,
                    weight=preference.weight,
                    matched=True,
                    is_unknown=False,
                    reason=f"Location '{lv}' matches preferred {preference.preferred_values}",
                    job_evidence=build_job_evidence(
                        posting,
                        posting_revision,
                        field_name,
                        quotation=lv,
                    ),
                )
        return PreferenceOutcome(
            rule_id=preference.rule_id,
            name=preference.name,
            field=field_name,
            weight=preference.weight,
            matched=False,
            is_unknown=False,
            reason=f"Stated locations [{', '.join(loc_values)}] do not match preferred {preference.preferred_values}",
        )

    # String / enum fields
    if isinstance(val, str):
        preferred_set = {normalize_lookup(pv) for pv in preference.preferred_values}
        # Exact match or phrase match
        if normalize_lookup(val) in preferred_set:
            return PreferenceOutcome(
                rule_id=preference.rule_id,
                name=preference.name,
                field=field_name,
                weight=preference.weight,
                matched=True,
                is_unknown=False,
                reason=f"Field '{field_name}' matches preferred '{val}'",
                job_evidence=build_job_evidence(posting, posting_revision, field_name, quotation=val),
            )
        for pv in preference.preferred_values:
            matches = find_literal_matches(val, pv)
            if matches:
                start, end, snippet = matches[0]
                return PreferenceOutcome(
                    rule_id=preference.rule_id,
                    name=preference.name,
                    field=field_name,
                    weight=preference.weight,
                    matched=True,
                    is_unknown=False,
                    reason=f"Field '{field_name}' contains preferred phrase '{pv}'",
                    job_evidence=build_job_evidence(
                        posting,
                        posting_revision,
                        field_name,
                        quotation=snippet,
                        span=(start, end),
                    ),
                )

        return PreferenceOutcome(
            rule_id=preference.rule_id,
            name=preference.name,
            field=field_name,
            weight=preference.weight,
            matched=False,
            is_unknown=False,
            reason=f"Field '{field_name}' did not match preferred values",
        )

    return PreferenceOutcome(
        rule_id=preference.rule_id,
        name=preference.name,
        field=field_name,
        weight=preference.weight,
        matched=False,
        is_unknown=False,
        reason=f"Preference could not be evaluated on field type {type(val).__name__}",
    )


def evaluate_all_preferences(
    policy: Union[EffectivePolicy, SearchPolicy],
    posting: NormalizedPosting,
    posting_revision: str,
) -> list[PreferenceOutcome]:
    """Evaluate all configured soft preferences."""
    raw_policy = policy if isinstance(policy, SearchPolicy) else policy.policy
    return [
        evaluate_preference_rule(pref, posting, posting_revision)
        for pref in raw_policy.preferences
    ]

