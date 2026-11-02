"""Broad keyword matching and alias expansion across title and description."""

from __future__ import annotations

from typing import Union

from job_automation.assessment.literal_matching import find_literal_matches
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.models import EffectivePolicy
from job_automation.policy.vocabulary import validate_vocabulary


class KeywordMatch:
    """Represents a matched keyword or alias."""

    def __init__(
        self,
        keyword: str,
        field: str,
        start: int,
        end: int,
        snippet: str,
    ) -> None:
        self.keyword = keyword
        self.field = field
        self.start = start
        self.end = end
        self.snippet = snippet


def expand_keyword_terms(
    term: str,
    policy: Union[EffectivePolicy, SearchPolicy],
) -> list[str]:
    """Expand a term with its declared role and skill aliases."""
    raw_policy = policy if isinstance(policy, SearchPolicy) else policy.policy
    vocab, _ = validate_vocabulary(raw_policy.role_aliases, raw_policy.skill_aliases)

    terms = [term]

    # Check role aliases
    for group in vocab.role_groups.values():
        if term.lower() == group.canonical_display.lower() or any(term.lower() == a.lower() for a in group.aliases_display):
            terms.append(group.canonical_display)
            terms.extend(group.aliases_display)

    # Check skill aliases
    for group in vocab.skill_groups.values():
        if term.lower() == group.canonical_display.lower() or any(term.lower() == a.lower() for a in group.aliases_display):
            terms.append(group.canonical_display)
            terms.extend(group.aliases_display)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for t in terms:
        t_clean = t.strip()
        if t_clean and t_clean.lower() not in seen:
            seen.add(t_clean.lower())
            deduped.append(t_clean)

    return deduped


def evaluate_broad_keywords(
    policy: Union[EffectivePolicy, SearchPolicy],
    posting: NormalizedPosting,
) -> tuple[list[KeywordMatch], list[str]]:
    """Search for broad keywords (and aliases) across posting title and clean description.

    Returns:
        tuple[list[KeywordMatch], list[str]]: (matches, misses)
    """
    raw_policy = policy if isinstance(policy, SearchPolicy) else policy.policy
    broad_kws = raw_policy.relevance_configuration.broad_keywords

    if not broad_kws:
        return [], []

    matches: list[KeywordMatch] = []
    misses: list[str] = []

    for kw in broad_kws:
        expanded_variants = expand_keyword_terms(kw, policy)
        kw_matched = False

        # 1. Search in title first
        for variant in expanded_variants:
            t_matches = find_literal_matches(posting.title, variant)
            if t_matches:
                start, end, snippet = t_matches[0]
                matches.append(KeywordMatch(kw, "title", start, end, snippet))
                kw_matched = True
                break

        if kw_matched:
            continue

        # 2. Search in clean description
        for variant in expanded_variants:
            d_matches = find_literal_matches(posting.description_clean, variant)
            if d_matches:
                start, end, snippet = d_matches[0]
                matches.append(KeywordMatch(kw, "description_clean", start, end, snippet))
                kw_matched = True
                break

        if not kw_matched:
            misses.append(kw)

    return matches, misses

