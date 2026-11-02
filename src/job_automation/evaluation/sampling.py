"""Stratified sampling without replacement for rejected jobs (EVAL-01-S07).

Enforces:
- Deterministic, seeded sampling without replacement.
- Row-order invariance: identical frame and seed yield identical samples regardless of input order.
- Non-overlapping primary strata: hard_failure, exclusion, missing_policy, semantic_gap, low_score.
- Accurate inclusion probabilities per stratum.
- Small strata use census (100% sampling).
- Empty frames produce explicit empty results.
"""

from __future__ import annotations

import random
from typing import Sequence

from job_automation.evaluation.population_reader import (
    PopulationFilterResult,
    RejectedJobCandidate,
)
from job_automation.evaluation.records import SampleManifest


def sample_rejected_population(
    population: PopulationFilterResult,
    target_sample_size: int = 50,
    seed: int = 42,
    stratum_quotas: dict[str, int] | None = None,
) -> SampleManifest:
    """Sample rejected job assessments using seeded stratified sampling without replacement.

    Guarantees:
    - Same frame_hash and seed produces the exact same selected IDs.
    - Zero modification of production data.
    """
    total_pop = len(population.eligible_candidates)
    if total_pop == 0:
        return SampleManifest(
            population_cohort_id=population.cohort_id,
            population_size=0,
            sample_size=0,
            sampling_seed=seed,
            stratification_summary={},
            inclusion_probabilities={},
            selected_case_ids=[],
            frame_hash=population.frame_hash,
        )

    # 1. Group candidates by primary non-overlapping stratum
    strata: dict[str, list[RejectedJobCandidate]] = {}
    for cand in population.eligible_candidates:
        cat = cand.rejection_category
        strata.setdefault(cat, []).append(cand)

    # 2. Sort within each stratum for row-order invariance
    for cat in strata:
        strata[cat].sort(key=lambda c: (str(c.canonical_job_id), c.posting_revision))

    stratification_summary: dict[str, int] = {cat: len(items) for cat, items in strata.items()}
    inclusion_probabilities: dict[str, float] = {}
    selected_ids: list[str] = []

    # 3. Determine sample size per stratum
    # If explicit quotas not provided, distribute proportionally with minimum 1 per stratum
    for cat, items in sorted(strata.items()):
        n_pop = len(items)
        if stratum_quotas and cat in stratum_quotas:
            k = min(n_pop, max(0, stratum_quotas[cat]))
        else:
            proportion = n_pop / total_pop
            k = min(n_pop, max(1, round(target_sample_size * proportion)))

        # Seed per stratum for independent reproducible draws
        rng = random.Random(f"{seed}_{cat}_{population.frame_hash[:16]}")
        if k >= n_pop:
            # Census for this stratum
            sampled = items[:]
            inc_prob = 1.0
        else:
            sampled = rng.sample(items, k)
            inc_prob = round(k / n_pop, 4)

        inclusion_probabilities[cat] = inc_prob
        selected_ids.extend([str(c.canonical_job_id) for c in sampled])

    # Sort selected IDs for deterministic manifest ordering
    selected_ids.sort()

    return SampleManifest(
        population_cohort_id=population.cohort_id,
        population_size=total_pop,
        sample_size=len(selected_ids),
        sampling_seed=seed,
        stratification_summary=stratification_summary,
        inclusion_probabilities=inclusion_probabilities,
        selected_case_ids=selected_ids,
        frame_hash=population.frame_hash,
    )

