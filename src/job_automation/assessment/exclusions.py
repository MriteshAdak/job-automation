"""Evaluation of explicit exclusions and negative keywords with conservative review routing."""

from __future__ import annotations

from typing import Union

from job_automation.assessment.evidence import build_job_evidence
from job_automation.assessment.literal_matching import find_literal_matches
from job_automation.assessment.models import ExclusionOutcome
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.models import EffectivePolicy
from job_automation.policy.vocabulary import normalize_lookup


def evaluate_exclusions(
    policy: Union[EffectivePolicy, SearchPolicy],
    posting: NormalizedPosting,
    posting_revision: str,
) -> list[ExclusionOutcome]:
    """Evaluate explicit exclusions and negative keywords.

    Definitive company or title matches cause immediate rejection with evidence.
    Incidental description mentions route to human review without silent rejection.
    """
    raw_policy = policy if isinstance(policy, SearchPolicy) else policy.policy
    outcomes: list[ExclusionOutcome] = []

    # Combined list of exclusion terms
    exclusion_terms = list(raw_policy.exclusions)
    negative_keywords = list(raw_policy.relevance_configuration.negative_keywords)

    all_negative_terms = exclusion_terms + [k for k in negative_keywords if k not in exclusion_terms]

    norm_company = normalize_lookup(posting.company_name_hint)

    for term in all_negative_terms:
        clean_term = term.strip()
        if not clean_term:
            continue

        norm_term = normalize_lookup(clean_term)

        # 1. Exact or phrase match on company name (definitive rejection)
        if norm_company == norm_term or norm_term in norm_company:
            ev = build_job_evidence(
                posting,
                posting_revision,
                "company_name_hint",
                quotation=posting.company_name_hint,
            )
            outcomes.append(
                ExclusionOutcome(
                    excluded=True,
                    reason=f"Employer '{posting.company_name_hint}' matches excluded entity '{clean_term}'",
                    matched_term=clean_term,
                    field="company_name_hint",
                    is_review_proposal=False,
                    job_evidence=ev,
                )
            )
            continue

        # 2. Affirmative match in job title (definitive rejection)
        title_matches = find_literal_matches(posting.title, clean_term)
        if title_matches:
            start, end, snippet = title_matches[0]
            ev = build_job_evidence(
                posting,
                posting_revision,
                "title",
                quotation=snippet,
                span=(start, end),
            )
            outcomes.append(
                ExclusionOutcome(
                    excluded=True,
                    reason=f"Job title '{posting.title}' matches excluded term '{clean_term}'",
                    matched_term=clean_term,
                    field="title",
                    is_review_proposal=False,
                    job_evidence=ev,
                )
            )
            continue

        # 3. Mention in description (conservative: propose review, do not auto-reject)
        desc_matches = find_literal_matches(posting.description_clean, clean_term)
        if desc_matches:
            start, end, snippet = desc_matches[0]
            ev = build_job_evidence(
                posting,
                posting_revision,
                "description_clean",
                quotation=snippet,
                span=(start, end),
            )
            outcomes.append(
                ExclusionOutcome(
                    excluded=False,
                    reason=f"Term '{clean_term}' detected in description; proposing human review for context",
                    matched_term=clean_term,
                    field="description_clean",
                    is_review_proposal=True,
                    job_evidence=ev,
                )
            )

    return outcomes

