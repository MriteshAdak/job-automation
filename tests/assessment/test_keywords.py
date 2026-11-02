"""Tests for literal matching, token boundaries, and alias expansion (MATCH-01-S06)."""

from __future__ import annotations

import pytest

from job_automation.assessment.keywords import evaluate_broad_keywords, expand_keyword_terms
from job_automation.assessment.literal_matching import (
    contains_literal_phrase,
    find_literal_matches,
)


class TestKeywords:
    def test_token_boundary_precision(self) -> None:
        # Java vs JavaScript
        text_js = "We are seeking a senior JavaScript developer."
        assert not contains_literal_phrase(text_js, "Java")
        assert contains_literal_phrase(text_js, "JavaScript")

        # Go vs Ongoing
        text_go = "This is an ongoing project using Go and Python."
        matches_go = find_literal_matches(text_go, "Go")
        assert len(matches_go) == 1
        assert matches_go[0][2] == "Go"

    def test_distinctive_punctuation_preserved(self) -> None:
        # C++
        text_cpp = "Requires 5+ years of C++ experience."
        matches_cpp = find_literal_matches(text_cpp, "C++")
        assert len(matches_cpp) == 1
        assert matches_cpp[0][2] == "C++"

        # C#
        text_cs = "Experience with C# and .NET Core."
        assert contains_literal_phrase(text_cs, "C#")
        assert contains_literal_phrase(text_cs, ".NET")

    def test_german_umlauts_and_alias_expansion(self, make_posting, make_policy) -> None:
        policy = make_policy(
            role_aliases={"Projektleiter": ["Project Manager", "Projektleiterin"]},
            broad_keywords=["Projektleiter"],
        )

        posting = make_posting(title="Erfahrene Projektleiterin (m/w/d) gesucht")
        matches, misses = evaluate_broad_keywords(policy, posting)
        assert len(matches) == 1
        assert matches[0].keyword == "Projektleiter"
        assert matches[0].field == "title"
        assert len(misses) == 0

    def test_broad_keyword_recall_across_title_and_description(
        self, make_posting, make_policy
    ) -> None:
        policy = make_policy(broad_keywords=["Python", "PostgreSQL", "Kubernetes"])
        posting = make_posting(
            title="Senior Backend Engineer",
            description="We build scalable services with Python and PostgreSQL on AWS.",
        )

        matches, misses = evaluate_broad_keywords(policy, posting)
        hit_keywords = [m.keyword for m in matches]
        assert "Python" in hit_keywords
        assert "PostgreSQL" in hit_keywords
        assert "Kubernetes" in misses

