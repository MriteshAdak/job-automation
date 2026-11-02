"""End-to-end integration tests for MATCH-01 deterministic assessment.

Exercises the full pipeline:
- Real SearchPolicy loaded and validated via PolicyService.
- NormalizedPosting instances (including via DefaultNormalizer).
- Approved ProfileSnapshot and CandidateEligibility.
- Execution via AssessmentService and RuleEvaluator Protocol conformance.
- Matrix: Eligible, Hard Fail, Missing Fact (Review), Waived Fact (Eligible), Excluded Employer (Rejected).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from job_automation.assessment.models import EVALUATOR_VERSION
from job_automation.assessment.service import AssessmentService, DeterministicRuleEvaluator
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    HardCriterionResult,
    SalaryPeriod,
    WorkplaceType,
)
from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.interfaces import RuleEvaluator
from job_automation.contracts.postings import (
    JobCompensation,
    NormalizedPosting,
    SourceJobDraft,
    StructuredLocation,
)
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.normalization.service import DefaultNormalizer
from job_automation.policy.service import PolicyService


class TestAssessmentIntegration:
    @pytest.fixture
    def tech_policy(self):
        """Load valid technical search policy fixture."""
        fixture_path = Path("tests/fixtures/policy/valid_tech.json")
        res = PolicyService.load_and_validate(fixture_path)
        assert res.is_valid, f"Policy validation failed: {res.issues}"
        assert res.effective_policy is not None
        return res.effective_policy

    @pytest.fixture
    def assessment_fixtures_dir(self) -> Path:
        return Path("tests/fixtures/assessment")

    def test_fixtures_catalog_matrix(
        self, tech_policy, assessment_fixtures_dir: Path, make_profile
    ) -> None:
        """Verify evaluation outcomes against synthetic catalog fixtures."""
        service = AssessmentService()
        profile = make_profile(auth_countries=["DE"], remote_eligible=True)

        # Policy without min_score_threshold for purely deterministic gating
        rel_cfg = tech_policy.policy.relevance_configuration.model_copy(
            update={"min_score_threshold": None}
        )
        policy = tech_policy.model_copy(
            update={"policy": tech_policy.policy.model_copy(update={"relevance_configuration": rel_cfg})}
        )

        # 1. eligible_posting.json -> ELIGIBLE
        p1 = NormalizedPosting.model_validate_json(
            (assessment_fixtures_dir / "eligible_posting.json").read_text(encoding="utf-8")
        )
        res1 = service.evaluate_posting(
            canonical_job_id=uuid.uuid4(),
            posting_revision=p1.raw_content_hash,
            posting=p1,
            policy=policy,
            profile=profile,
        )
        assert res1.final_disposition == AssessmentDisposition.ELIGIBLE

        # 2. hard_fail_posting.json -> REJECTED
        p2 = NormalizedPosting.model_validate_json(
            (assessment_fixtures_dir / "hard_fail_posting.json").read_text(encoding="utf-8")
        )
        res2 = service.evaluate_posting(
            canonical_job_id=uuid.uuid4(),
            posting_revision=p2.raw_content_hash,
            posting=p2,
            policy=policy,
            profile=profile,
        )
        assert res2.final_disposition == AssessmentDisposition.REJECTED

        # 3. missing_compensation_posting.json (with compensation rule requiring unknown) -> REVIEW
        from job_automation.contracts.policy import HardCriterion
        from job_automation.policy.models import EffectiveMissingAction
        comp_crit = HardCriterion(
            criterion_id="crit_comp",
            name="Salary Requirement",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
            on_missing="unknown",
        )
        policy_with_comp = policy.model_copy(
            update={
                "policy": policy.policy.model_copy(
                    update={"hard_criteria": list(policy.policy.hard_criteria) + [comp_crit]}
                ),
                "effective_missing_actions": {
                    **policy.effective_missing_actions,
                    "crit_comp": EffectiveMissingAction(action="unknown", source="explicit_rule"),
                },
            }
        )
        p3 = NormalizedPosting.model_validate_json(
            (assessment_fixtures_dir / "missing_compensation_posting.json").read_text(encoding="utf-8")
        )
        res3 = service.evaluate_posting(
            canonical_job_id=uuid.uuid4(),
            posting_revision=p3.raw_content_hash,
            posting=p3,
            policy=policy_with_comp,
            profile=profile,
        )
        assert res3.final_disposition == AssessmentDisposition.REVIEW

        # 4. excluded_employer_posting.json -> REJECTED
        p4 = NormalizedPosting.model_validate_json(
            (assessment_fixtures_dir / "excluded_employer_posting.json").read_text(encoding="utf-8")
        )
        res4 = service.evaluate_posting(
            canonical_job_id=uuid.uuid4(),
            posting_revision=p4.raw_content_hash,
            posting=p4,
            policy=policy,
            profile=profile,
        )
        assert res4.final_disposition == AssessmentDisposition.REJECTED


    @pytest.fixture
    def normalizer(self):
        return DefaultNormalizer()

    def test_protocol_conformance(self) -> None:
        """DeterministicRuleEvaluator must satisfy RuleEvaluator Protocol."""
        evaluator = DeterministicRuleEvaluator()
        assert isinstance(evaluator, RuleEvaluator)

    def test_scenario_eligible_job(
        self, tech_policy, make_posting, make_profile
    ) -> None:
        """Job meets hard criteria, keywords match, candidate authorized -> ELIGIBLE."""
        # Unset min_score_threshold to allow pure deterministic ELIGIBLE
        rel_cfg = tech_policy.policy.relevance_configuration.model_copy(
            update={"min_score_threshold": None}
        )
        search_pol = tech_policy.policy.model_copy(
            update={"relevance_configuration": rel_cfg}
        )
        policy = tech_policy.model_copy(update={"policy": search_pol})

        posting = make_posting(
            title="Senior Backend Developer (Python)",
            description="We are seeking a senior engineer with Python and microservices experience.",
            company="Modern Cloud Labs",
            country="DE",
            city="Berlin",
            workplace_type=WorkplaceType.REMOTE,
            remote_restrictions=["DE"],
            compensation=JobCompensation(
                min_amount=Decimal("75000"),
                max_amount=Decimal("90000"),
                currency="EUR",
                period=SalaryPeriod.YEARLY,
            ),
        )
        profile = make_profile(auth_countries=["DE"], remote_eligible=True)

        service = AssessmentService()
        job_id = uuid.uuid4()
        assessment = service.evaluate_posting(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )

        assert assessment.final_disposition == AssessmentDisposition.ELIGIBLE
        assert assessment.relevance_decision == AssessmentDisposition.ELIGIBLE
        assert assessment.assessment_method == AssessmentMethod.RULES
        assert assessment.model_metadata is None
        assert "pass" in assessment.summary_reason.lower() or "eligible" in assessment.summary_reason.lower()

    def test_scenario_min_score_threshold_routes_to_review(
        self, tech_policy, make_posting, make_profile
    ) -> None:
        """When policy configures min_score_threshold (e.g. 75.0), deterministic routes to REVIEW."""
        assert tech_policy.policy.relevance_configuration.min_score_threshold == 75.0
        posting = make_posting(
            title="Senior Backend Developer (Python)",
            description="We are seeking a senior engineer with Python and microservices experience.",
            company="Modern Cloud Labs",
            country="DE",
            city="Berlin",
            workplace_type=WorkplaceType.REMOTE,
            remote_restrictions=["DE"],
        )
        profile = make_profile(auth_countries=["DE"], remote_eligible=True)

        service = AssessmentService()
        assessment = service.evaluate_posting(
            canonical_job_id=uuid.uuid4(),
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=tech_policy,
            profile=profile,
        )

        assert assessment.final_disposition == AssessmentDisposition.REVIEW
        assert "min_score_threshold" in assessment.summary_reason

    def test_scenario_missing_fact_triggers_review(
        self, tech_policy, make_posting, make_profile
    ) -> None:
        """When compensation is missing and missing_information_behavior is 'unknown' -> REVIEW."""
        from job_automation.contracts.policy import HardCriterion
        from job_automation.policy.models import EffectiveMissingAction

        new_crit = HardCriterion(
            criterion_id="crit_comp",
            name="Salary Requirement",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
            on_missing="unknown",
        )
        hard_criteria = list(tech_policy.policy.hard_criteria) + [new_crit]
        rel_cfg = tech_policy.policy.relevance_configuration.model_copy(
            update={"min_score_threshold": None}
        )
        search_pol = tech_policy.policy.model_copy(
            update={"hard_criteria": hard_criteria, "relevance_configuration": rel_cfg}
        )
        missing_actions = dict(tech_policy.effective_missing_actions)
        missing_actions["crit_comp"] = EffectiveMissingAction(
            action="unknown", source="explicit_rule"
        )
        policy = tech_policy.model_copy(
            update={"policy": search_pol, "effective_missing_actions": missing_actions}
        )

        posting = make_posting(
            title="Backend Developer",
            description="Python engineer needed for distributed systems.",
            country="DE",
            workplace_type=WorkplaceType.HYBRID,
            compensation=None,  # Missing compensation!
        )
        profile = make_profile(auth_countries=["DE"])

        service = AssessmentService()
        job_id = uuid.uuid4()
        assessment = service.evaluate_posting(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )

        assert assessment.final_disposition == AssessmentDisposition.REVIEW
        assert any("compensation" in u.lower() for u in assessment.identified_unknowns)

    def test_scenario_waived_missing_fact_passes(
        self, tech_policy, make_posting, make_profile
    ) -> None:
        """When missing compensation is explicitly waived (on_missing='pass') -> ELIGIBLE."""
        from job_automation.contracts.policy import HardCriterion
        from job_automation.policy.models import EffectiveMissingAction

        new_crit = HardCriterion(
            criterion_id="crit_comp",
            name="Salary Requirement",
            field="compensation",
            operator="gte",
            expected_value={"amount": 60000, "currency": "EUR", "period": "yearly"},
            on_missing="pass",
        )
        hard_criteria = list(tech_policy.policy.hard_criteria) + [new_crit]
        rel_cfg = tech_policy.policy.relevance_configuration.model_copy(
            update={"min_score_threshold": None}
        )
        search_pol = tech_policy.policy.model_copy(
            update={"hard_criteria": hard_criteria, "relevance_configuration": rel_cfg}
        )
        missing_actions = dict(tech_policy.effective_missing_actions)
        missing_actions["crit_comp"] = EffectiveMissingAction(
            action="pass", source="explicit_rule"
        )
        policy = tech_policy.model_copy(
            update={"policy": search_pol, "effective_missing_actions": missing_actions}
        )

        posting = make_posting(
            title="Backend Developer",
            description="Python engineer needed for cloud services.",
            country="DE",
            workplace_type=WorkplaceType.HYBRID,
            compensation=None,  # Missing compensation, but waived!
        )
        profile = make_profile(auth_countries=["DE"])

        service = AssessmentService()
        job_id = uuid.uuid4()
        assessment = service.evaluate_posting(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )

        assert assessment.final_disposition == AssessmentDisposition.ELIGIBLE
        crit_outcomes = [o for o in assessment.rule_outcomes if o.criterion_id == "crit_comp"]
        assert len(crit_outcomes) == 1
        assert crit_outcomes[0].result == HardCriterionResult.PASS
        assert "waived" in crit_outcomes[0].reason.lower()

    def test_scenario_excluded_employer(
        self, tech_policy, make_posting, make_profile
    ) -> None:
        """Company matches exclusion list ('Gambling') -> REJECTED."""
        posting = make_posting(
            title="Python Backend Developer",
            company="Euro Gambling Entertainment AG",
            country="DE",
            workplace_type=WorkplaceType.REMOTE,
            remote_restrictions=["DE"],
        )
        profile = make_profile(auth_countries=["DE"])

        service = AssessmentService()
        job_id = uuid.uuid4()
        assessment = service.evaluate_posting(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=tech_policy,
            profile=profile,
        )

        assert assessment.final_disposition == AssessmentDisposition.REJECTED
        assert "Gambling" in assessment.summary_reason
