"""Tests for stratified sampling without replacement (EVAL-01-S07)."""

import random
import uuid
from job_automation.evaluation.population_reader import (
    PopulationFilterResult,
    RejectedJobCandidate,
)
from job_automation.evaluation.sampling import sample_rejected_population


def _make_candidate(cat: str, idx: int) -> RejectedJobCandidate:
    return RejectedJobCandidate(
        canonical_job_id=uuid.UUID(f"00000000-0000-0000-0000-{idx:012d}"),
        posting_revision="rev_1",
        title=f"Job {idx}",
        rejection_category=cat,
        primary_reason="Test reason",
    )


def test_sampling_seed_reproducibility_and_order_invariance():
    """Verify same seed produces same sample regardless of candidate list ordering."""
    candidates = []
    # 10 hard failures, 10 semantic gaps, 5 exclusions
    for i in range(1, 11):
        candidates.append(_make_candidate("hard_failure", i))
    for i in range(11, 21):
        candidates.append(_make_candidate("semantic_gap", i))
    for i in range(21, 26):
        candidates.append(_make_candidate("exclusion", i))

    pop_ordered = PopulationFilterResult(
        cohort_id="cohort_test",
        eligible_candidates=candidates[:],
        excluded_counts={},
        frame_hash="hash_stable",
    )

    shuffled_cands = candidates[:]
    random.Random(12345).shuffle(shuffled_cands)
    pop_shuffled = PopulationFilterResult(
        cohort_id="cohort_test",
        eligible_candidates=shuffled_cands,
        excluded_counts={},
        frame_hash="hash_stable",
    )

    sample_1 = sample_rejected_population(pop_ordered, target_sample_size=10, seed=42)
    sample_2 = sample_rejected_population(pop_shuffled, target_sample_size=10, seed=42)

    assert sample_1.selected_case_ids == sample_2.selected_case_ids
    assert sample_1.sample_size == sample_2.sample_size
    assert sample_1.inclusion_probabilities == sample_2.inclusion_probabilities


def test_small_stratum_census():
    """Verify small strata (fewer items than quota) take 100% census."""
    candidates = [
        _make_candidate("exclusion", 1),
        _make_candidate("exclusion", 2),
    ]
    for i in range(10, 30):
        candidates.append(_make_candidate("hard_failure", i))

    pop = PopulationFilterResult(
        cohort_id="cohort_test",
        eligible_candidates=candidates,
        excluded_counts={},
        frame_hash="hash_census",
    )

    manifest = sample_rejected_population(
        pop,
        target_sample_size=10,
        seed=42,
        stratum_quotas={"exclusion": 5},  # quota higher than population (2)
    )

    # Exclusion stratum has 2 items, quota 5 -> census (p=1.0)
    assert manifest.stratification_summary["exclusion"] == 2
    assert manifest.inclusion_probabilities["exclusion"] == 1.0


def test_empty_population_produces_empty_manifest():
    """Verify empty frame yields empty sample result."""
    pop = PopulationFilterResult(
        cohort_id="cohort_empty",
        eligible_candidates=[],
        excluded_counts={},
        frame_hash="hash_empty",
    )
    manifest = sample_rejected_population(pop, target_sample_size=10, seed=42)
    assert manifest.sample_size == 0
    assert manifest.population_size == 0
    assert manifest.selected_case_ids == []

