"""Unit tests for EvaluationCorpus (EVAL-01-S02)."""

import pytest

from job_automation.evaluation.corpus import (
    EvaluationCorpus,
    build_canonical_synthetic_cases,
    build_default_synthetic_policy,
    build_default_synthetic_profile,
)


def test_default_synthetic_corpus_integrity():
    """Verify default synthetic corpus loads, validates, and partitions correctly."""
    corpus = EvaluationCorpus.default_synthetic()
    assert len(corpus.cases) == 8

    # Check case retrieval
    c1 = corpus.get_case("case_01_eligible_senior_cpp")
    assert c1.posting.title == "Senior C++ Software Engineer"
    assert c1.gold_label.expected_score == 88.0

    # Check split filtering
    dev_cases = corpus.filter_split("development")
    held_cases = corpus.filter_split("held_out")
    all_cases = corpus.filter_split("all")

    assert len(dev_cases) + len(held_cases) == len(all_cases)
    assert len(all_cases) == 8


def test_corpus_raises_on_nonexistent_case():
    """Verify get_case raises KeyError on missing case."""
    corpus = EvaluationCorpus.default_synthetic()
    with pytest.raises(KeyError, match="not found in corpus"):
        corpus.get_case("non_existent_case_999")

