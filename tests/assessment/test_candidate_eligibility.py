"""Tests for explicit candidate eligibility verification (MATCH-01-S05)."""

from __future__ import annotations

import pytest

from job_automation.assessment.eligibility import evaluate_candidate_eligibility
from job_automation.assessment.models import FactualOutcome
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.profile import CandidateEligibility


class TestCandidateEligibility:
    def test_remote_job_candidate_not_eligible(self, make_posting) -> None:
        posting = make_posting(workplace_type=WorkplaceType.REMOTE, remote_restrictions=["DE"])
        eligibility = CandidateEligibility(remote_eligible=False, work_authorization_countries=["DE"])

        results = evaluate_candidate_eligibility(
            posting=posting,
            posting_revision=posting.raw_content_hash,
            eligibility=eligibility,
            profile_version="v1",
            permitted_facts=[],
        )

        remote_res = [r for r in results if r.check_name == "candidate_remote_eligible"][0]
        assert remote_res.factual_result == FactualOutcome.FAIL
        assert "not eligible for remote work" in remote_res.reason

    def test_remote_job_unstated_restrictions_produce_unknown(self, make_posting) -> None:
        # Remote job with unstated restrictions: remote does NOT imply worldwide
        posting = make_posting(workplace_type=WorkplaceType.REMOTE, remote_restrictions=[])
        eligibility = CandidateEligibility(remote_eligible=True, work_authorization_countries=["DE"])

        results = evaluate_candidate_eligibility(
            posting=posting,
            posting_revision=posting.raw_content_hash,
            eligibility=eligibility,
            profile_version="v1",
            permitted_facts=[],
        )

        restr_res = [r for r in results if r.check_name == "remote_restrictions_applicable"][0]
        assert restr_res.factual_result == FactualOutcome.UNKNOWN
        assert "unstated" in restr_res.reason

    def test_work_authorization_positive_and_unknown(self, make_posting) -> None:
        # Job in Germany
        posting_de = make_posting(country="DE")

        # 1. Candidate authorized in DE -> PASS
        elig_auth = CandidateEligibility(work_authorization_countries=["DE"])
        res_auth = evaluate_candidate_eligibility(
            posting=posting_de,
            posting_revision=posting_de.raw_content_hash,
            eligibility=elig_auth,
            profile_version="v1",
            permitted_facts=[],
        )
        auth_check = [r for r in res_auth if r.check_name == "work_authorization"][0]
        assert auth_check.factual_result == FactualOutcome.PASS

        # 2. Candidate authorization countries empty -> UNKNOWN (not proven failure)
        elig_empty = CandidateEligibility(work_authorization_countries=[])
        res_empty = evaluate_candidate_eligibility(
            posting=posting_de,
            posting_revision=posting_de.raw_content_hash,
            eligibility=elig_empty,
            profile_version="v1",
            permitted_facts=[],
        )
        empty_check = [r for r in res_empty if r.check_name == "work_authorization"][0]
        assert empty_check.factual_result == FactualOutcome.UNKNOWN
        assert "does not record explicit work authorization" in empty_check.reason

