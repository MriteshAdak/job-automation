"""Tests for intermediate trace capture (EVAL-01-S04)."""

import uuid
from dataclasses import dataclass
from typing import Any

from job_automation.assessment.llm_records import AssessmentRunResult
from job_automation.contracts.assessment import Assessment, RequirementFinding, RuleOutcome
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    FindingStatus,
    HardCriterionResult,
)
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.evaluation.capture import extract_arm_trace_data


@dataclass
class DummyBundle:
    strategy: ContextStrategy = ContextStrategy.JSON
    admitted_facts: list[Any] = None
    omitted_facts: list[Any] = None

    def __post_init__(self):
        if self.admitted_facts is None:
            self.admitted_facts = []
        if self.omitted_facts is None:
            self.omitted_facts = []


@dataclass
class DummyFact:
    fact_id: uuid.UUID


def test_extract_arm_trace_data():
    """Verify trace data correctly summarizes context bundle facts and cited findings."""
    f1 = uuid.uuid4()
    f2 = uuid.uuid4()
    bundle = DummyBundle(
        strategy=ContextStrategy.JSON,
        admitted_facts=[DummyFact(fact_id=f1)],
        omitted_facts=[DummyFact(fact_id=f2)],
    )

    asmt = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        posting_revision="rev1",
        profile_version="v1.0",
        policy_version="v1.0",
        assessment_method=AssessmentMethod.RULES,
        final_disposition=AssessmentDisposition.ELIGIBLE,
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        summary_reason="All criteria met",
        rule_outcomes=[
            RuleOutcome(
                criterion_id="r1",
                criterion_name="Criterion 1",
                result=HardCriterionResult.PASS,
                reason="Passed",
            )
        ],
        requirement_findings=[
            RequirementFinding(
                requirement_id="req1",
                requirement_text="Need F1",
                status=FindingStatus.MATCH,
                reason="Has F1",
                candidate_evidence=[
                    CandidateEvidenceReference(profile_version="v1.0", fact_id=f1)
                ],
            )
        ],
    )
    run_res = AssessmentRunResult(status="success", assessment=asmt, input_fingerprint="fp1")

    trace = extract_arm_trace_data(run_res, context_bundle=bundle)
    assert str(f1) in trace["admitted_fact_ids"]
    assert str(f2) in trace["omitted_fact_ids"]
    assert str(f1) in trace["final_cited_fact_ids"]
