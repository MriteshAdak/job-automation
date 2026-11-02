"""Tests for deterministic reproducibility of assessment outcomes (MATCH-01-S07)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from job_automation.assessment.inputs import bind_assessment_input
from job_automation.assessment.service import evaluate_deterministic
from job_automation.contracts.enums import AssessmentDisposition, SalaryPeriod, WorkplaceType
from job_automation.contracts.policy import HardCriterion, PreferenceRule
from job_automation.contracts.postings import JobCompensation


class TestReproducibility:
    def test_identical_inputs_produce_identical_c11_results(
        self, make_posting, make_profile, make_policy
    ) -> None:
        comp = JobCompensation(
            min_amount=Decimal("70000"),
            max_amount=Decimal("80000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        posting = make_posting(
            title="Senior Python Backend Developer",
            country="DE",
            city="Munich",
            workplace_type=WorkplaceType.HYBRID,
            compensation=comp,
        )
        profile = make_profile()
        policy = make_policy(
            hard_criteria=[
                HardCriterion(
                    criterion_id="crit_country",
                    name="Location DE",
                    field="locations.country",
                    operator="equals",
                    expected_value="DE",
                ),
                HardCriterion(
                    criterion_id="crit_sal",
                    name="Min Pay 60k",
                    field="compensation",
                    operator="gte",
                    expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
                ),
            ],
            preferences=[
                PreferenceRule(
                    rule_id="pref_hybrid",
                    name="Hybrid Preferred",
                    field="workplace_type",
                    weight=0.5,
                    preferred_values=["hybrid"],
                )
            ],
            broad_keywords=["Python", "Backend"],
        )

        exec_id = uuid.uuid4()
        can_id = uuid.uuid4()

        inp1 = bind_assessment_input(
            canonical_job_id=can_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
            execution_id=exec_id,
        )
        inp2 = bind_assessment_input(
            canonical_job_id=can_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
            execution_id=exec_id,
        )

        res1 = evaluate_deterministic(inp1)
        res2 = evaluate_deterministic(inp2)

        assert res1.final_disposition == AssessmentDisposition.ELIGIBLE
        assert res1.final_disposition == res2.final_disposition
        assert res1.relevance_decision == res2.relevance_decision
        assert res1.summary_reason == res2.summary_reason
        assert res1.assessment_id == exec_id
        assert res2.assessment_id == exec_id
        assert res1.model_dump_json() == res2.model_dump_json()

    def test_reproducibility_with_permuted_keywords_and_criteria(
        self, make_posting, make_profile, make_policy
    ) -> None:
        posting = make_posting(
            title="Senior Python Cloud Engineer",
            description="We build scalable cloud microservices using Python and AWS.",
        )
        profile = make_profile()

        crit1 = HardCriterion(
            criterion_id="c1",
            name="DE",
            field="locations.country",
            operator="equals",
            expected_value="DE",
        )
        crit2 = HardCriterion(
            criterion_id="c2",
            name="Senior",
            field="title",
            operator="contains",
            expected_value="Senior",
        )

        policy_a = make_policy(
            hard_criteria=[crit1, crit2],
            broad_keywords=["Python", "Cloud", "AWS"],
        )
        policy_b = make_policy(
            hard_criteria=[crit2, crit1],
            broad_keywords=["AWS", "Python", "Cloud"],
        )

        inp_a = bind_assessment_input(
            canonical_job_id=uuid.uuid4(),
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy_a,
            profile=profile,
        )
        inp_b = bind_assessment_input(
            canonical_job_id=uuid.uuid4(),
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy_b,
            profile=profile,
        )

        res_a = evaluate_deterministic(inp_a)
        res_b = evaluate_deterministic(inp_b)

        assert res_a.final_disposition == res_b.final_disposition
        assert res_a.relevance_decision == res_b.relevance_decision
        assert res_a.final_disposition == AssessmentDisposition.ELIGIBLE
        # The set of rule outcomes (by criterion_id) should be identical
        outcomes_a = {o.criterion_id: o.result for o in res_a.rule_outcomes}
        outcomes_b = {o.criterion_id: o.result for o in res_b.rule_outcomes}
        assert outcomes_a == outcomes_b
