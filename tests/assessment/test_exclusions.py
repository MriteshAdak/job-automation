"""Tests for explicit exclusions, negative keywords, and relevance disposition (MATCH-01-S06)."""

from __future__ import annotations

import pytest

from job_automation.assessment.exclusions import evaluate_exclusions
from job_automation.assessment.relevance import assess_relevance
from job_automation.contracts.enums import AssessmentDisposition


class TestExclusions:
    def test_employer_exclusion_causes_rejection(self, make_posting, make_policy) -> None:
        posting = make_posting(company="Spam Recruitment GmbH")
        policy = make_policy(exclusions=["Spam Recruitment GmbH", "Unwanted Corp"])

        exclusions = evaluate_exclusions(policy, posting, posting.raw_content_hash)
        assert len(exclusions) == 1
        assert exclusions[0].excluded is True
        assert exclusions[0].field == "company_name_hint"
        assert exclusions[0].job_evidence is not None

        rel, _ = assess_relevance(policy, posting, posting.raw_content_hash)
        assert rel.decision == AssessmentDisposition.REJECTED
        assert "matches excluded entity" in rel.reason

    def test_title_exclusion_causes_rejection(self, make_posting, make_policy) -> None:
        posting = make_posting(title="Working Student Software Testing (Intern)")
        policy = make_policy(negative_keywords=["Intern", "Working Student"])

        exclusions = evaluate_exclusions(policy, posting, posting.raw_content_hash)
        assert any(e.excluded and e.field == "title" for e in exclusions)

        rel, _ = assess_relevance(policy, posting, posting.raw_content_hash)
        assert rel.decision == AssessmentDisposition.REJECTED

    def test_description_incidental_mention_proposes_review(self, make_posting, make_policy) -> None:
        # Posting is regular full-time, but description says "We do not offer unpaid internships"
        posting = make_posting(
            title="Senior Python Developer",
            description="We offer competitive salaries. Note: we do not accept unpaid positions.",
        )
        policy = make_policy(exclusions=["unpaid"])

        exclusions = evaluate_exclusions(policy, posting, posting.raw_content_hash)
        assert len(exclusions) == 1
        assert exclusions[0].excluded is False
        assert exclusions[0].is_review_proposal is True
        assert exclusions[0].field == "description_clean"

        rel, _ = assess_relevance(policy, posting, posting.raw_content_hash)
        assert rel.decision == AssessmentDisposition.REVIEW
        assert "proposing human review" in rel.reason

    def test_no_broad_keyword_hits_routes_to_review(self, make_posting, make_policy) -> None:
        # Job description has zero Python keywords (e.g. general office role)
        posting = make_posting(
            title="Office Manager",
            description="General office coordination, billing, and scheduling.",
        )
        policy = make_policy(broad_keywords=["Python", "Django", "FastAPI"])

        rel, _ = assess_relevance(policy, posting, posting.raw_content_hash)
        assert rel.decision == AssessmentDisposition.REVIEW
        assert "Inconclusive relevance" in rel.reason

    def test_min_score_threshold_routes_to_review(self, make_posting, make_policy) -> None:
        posting = make_posting(title="Python Developer", description="Python backend engineer.")
        policy = make_policy(min_score_threshold=75.0)

        rel, _ = assess_relevance(policy, posting, posting.raw_content_hash)
        assert rel.decision == AssessmentDisposition.REVIEW
        assert "min_score_threshold" in rel.reason

