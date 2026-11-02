"""Relevance assessment synthesizing broad keywords, exclusions, and soft preferences."""

from __future__ import annotations

from typing import Union

from job_automation.assessment.evidence import build_job_evidence
from job_automation.assessment.exclusions import evaluate_exclusions
from job_automation.assessment.keywords import evaluate_broad_keywords
from job_automation.assessment.models import ExclusionOutcome, RelevanceAssessmentResult
from job_automation.contracts.enums import AssessmentDisposition
from job_automation.contracts.evidence import JobEvidenceReference
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.models import EffectivePolicy


def assess_relevance(
    policy: Union[EffectivePolicy, SearchPolicy],
    posting: NormalizedPosting,
    posting_revision: str,
) -> tuple[RelevanceAssessmentResult, list[ExclusionOutcome]]:
    """Evaluate broad relevance signals, exclusions, and keyword recall.

    Returns:
        tuple[RelevanceAssessmentResult, list[ExclusionOutcome]]
    """
    raw_policy = policy if isinstance(policy, SearchPolicy) else policy.policy
    exclusions = evaluate_exclusions(policy, posting, posting_revision)

    # 1. Check definitive exclusions (disposition REJECTED)
    for exc in exclusions:
        if exc.excluded:
            ev_list = [exc.job_evidence] if exc.job_evidence else []
            return (
                RelevanceAssessmentResult(
                    decision=AssessmentDisposition.REJECTED,
                    negative_keyword_hits=[exc.matched_term] if exc.matched_term else [],
                    reason=exc.reason or "Posting matches explicit exclusion",
                    job_evidence=ev_list,
                ),
                exclusions,
            )

    # 2. Check ambiguous review proposals (disposition REVIEW)
    for exc in exclusions:
        if exc.is_review_proposal:
            ev_list = [exc.job_evidence] if exc.job_evidence else []
            return (
                RelevanceAssessmentResult(
                    decision=AssessmentDisposition.REVIEW,
                    negative_keyword_hits=[exc.matched_term] if exc.matched_term else [],
                    reason=exc.reason or "Incidental negative keyword mention in description requires review",
                    job_evidence=ev_list,
                ),
                exclusions,
            )

    # 3. Check min_score_threshold: deterministic assessment cannot compute model score
    rel_config = raw_policy.relevance_configuration
    if rel_config.min_score_threshold is not None:
        return (
            RelevanceAssessmentResult(
                decision=AssessmentDisposition.REVIEW,
                reason=(
                    f"Policy configures min_score_threshold={rel_config.min_score_threshold}, "
                    "but deterministic rules assessment does not evaluate a model score; routed to review"
                ),
            ),
            exclusions,
        )

    # 4. Broad keywords matching
    matches, misses = evaluate_broad_keywords(policy, posting)

    broad_configured = len(rel_config.broad_keywords) > 0

    if not broad_configured:
        # No broad keywords configured: relevance gate passes
        return (
            RelevanceAssessmentResult(
                decision=AssessmentDisposition.ELIGIBLE,
                reason="No broad keyword filters configured; relevance criteria satisfied",
            ),
            exclusions,
        )

    if matches:
        ev_list: list[JobEvidenceReference] = []
        for m in matches:
            ev = build_job_evidence(
                posting,
                posting_revision,
                m.field,
                quotation=m.snippet,
                span=(m.start, m.end),
            )
            if ev:
                ev_list.append(ev)

        hit_names = [m.keyword for m in matches]
        return (
            RelevanceAssessmentResult(
                decision=AssessmentDisposition.ELIGIBLE,
                broad_keyword_hits=hit_names,
                broad_keyword_misses=misses,
                reason=f"Matched broad keywords: {', '.join(hit_names)}",
                job_evidence=ev_list,
            ),
            exclusions,
        )

    # Broad keywords were configured, but NONE matched
    # Inconclusive relevance -> REVIEW (NOT REJECTED)
    return (
        RelevanceAssessmentResult(
            decision=AssessmentDisposition.REVIEW,
            broad_keyword_misses=misses,
            reason=(
                "Inconclusive relevance: no configured broad keywords matched advert title or description; "
                "routed to human/LLM review rather than discarding"
            ),
        ),
        exclusions,
    )

