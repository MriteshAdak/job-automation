"""Tests for requirement-level failure and success attribution (EVAL-01-S05)."""

import uuid
from job_automation.contracts.assessment import RequirementCategory, RequirementFinding
from job_automation.contracts.enums import ContextStrategy, FindingStatus
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.evaluation.attribution import (
    AttributionCategory,
    attribute_requirement_outcome,
)
from job_automation.evaluation.records import GoldRequirementLabel


def _make_gold_req(
    req_id: str = "req_c_plus_plus",
    gold_status: FindingStatus = FindingStatus.MATCH,
    sufficient_sets: list[list[str]] | None = None,
    contradictory_ids: list[str] | None = None,
) -> GoldRequirementLabel:
    return GoldRequirementLabel(
        requirement_id=req_id,
        category=RequirementCategory.SKILL,
        text="5+ years C++ programming",
        gold_status=gold_status,
        sufficient_evidence_sets=sufficient_sets if sufficient_sets is not None else [["fact_cpp_1"]],
        contradictory_fact_ids=contradictory_ids or [],
        source_spans=[],
    )


def test_attribution_extraction_loss():
    """Unextracted requirement is attributed to extraction loss, not retrieval."""
    gold = _make_gold_req()
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=False,
        finding=None,
        strategy=ContextStrategy.RAG,
        admitted_fact_ids=set(),
        retrieved_fact_ids={"fact_cpp_1"},
    )
    assert attr.primary_stage == AttributionCategory.EXTRACTION_LOSS
    assert attr.extracted is False


def test_attribution_no_evidence_expected():
    """Gap requirement with no evidence expected is correctly attributed."""
    gold = _make_gold_req(
        req_id="req_sap",
        gold_status=FindingStatus.GAP,
        sufficient_sets=[],
    )
    finding = RequirementFinding(
        requirement_id="req_sap",
        requirement_text="SAP experience",
        status=FindingStatus.GAP,
        reason="No SAP experience documented",
        candidate_evidence=[],
    )
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=True,
        finding=finding,
        strategy=ContextStrategy.RAG,
        admitted_fact_ids=set(),
        retrieved_fact_ids=set(),
    )
    assert attr.primary_stage == AttributionCategory.NO_EVIDENCE_EXPECTED


def test_attribution_retrieval_loss_rag():
    """Fact absent from raw vector retrieval is attributed to retrieval loss."""
    gold = _make_gold_req(sufficient_sets=[["fact_cpp_1"]])
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=True,
        finding=None,
        strategy=ContextStrategy.RAG,
        admitted_fact_ids=set(),
        retrieved_fact_ids={"fact_python_1", "fact_java_1"},
    )
    assert attr.primary_stage == AttributionCategory.RETRIEVAL_LOSS


def test_attribution_ranking_loss_rag():
    """Fact retrieved in search but dropped by ranking/top-k is ranking loss."""
    gold = _make_gold_req(sufficient_sets=[["fact_cpp_1"]])
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=True,
        finding=None,
        strategy=ContextStrategy.RAG,
        admitted_fact_ids=set(),
        retrieved_fact_ids={"fact_cpp_1", "fact_python_1"},
        ranked_fact_ids={"fact_python_1"},  # cpp was dropped
    )
    assert attr.primary_stage == AttributionCategory.RANKING_LOSS


def test_attribution_budget_packing_loss():
    """Fact survived ranking but was omitted from admitted prompt due to budget."""
    gold = _make_gold_req(sufficient_sets=[["fact_cpp_1"]])
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=True,
        finding=None,
        strategy=ContextStrategy.RAG,
        admitted_fact_ids={"fact_python_1"},
        retrieved_fact_ids={"fact_cpp_1"},
        ranked_fact_ids={"fact_cpp_1"},
    )
    assert attr.primary_stage == AttributionCategory.BUDGET_PACKING_LOSS


def test_attribution_inference_use_loss():
    """Fact was admitted in prompt context, but model failed to cite it."""
    gold = _make_gold_req(sufficient_sets=[["fact_cpp_1"]])
    finding = RequirementFinding(
        requirement_id="req_c_plus_plus",
        requirement_text="C++",
        status=FindingStatus.GAP,
        reason="Did not find C++",
        candidate_evidence=[],
    )
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=True,
        finding=finding,
        strategy=ContextStrategy.JSON,
        admitted_fact_ids={"fact_cpp_1"},
    )
    assert attr.primary_stage == AttributionCategory.INFERENCE_USE_LOSS


def test_attribution_semantic_distortion():
    """Fact was cited, but model reached a contradictory or distorted conclusion."""
    gold = _make_gold_req(
        sufficient_sets=[["fact_cpp_1"]],
        contradictory_ids=["fact_junior_cpp"],
    )
    finding = RequirementFinding(
        requirement_id="req_c_plus_plus",
        requirement_text="C++",
        status=FindingStatus.MATCH,
        reason="Has junior C++ experience",
        candidate_evidence=[
            CandidateEvidenceReference(
                profile_version="v1",
                fact_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            )
        ],
    )
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=True,
        finding=finding,
        strategy=ContextStrategy.JSON,
        admitted_fact_ids={"fact_cpp_1", "11111111-1111-1111-1111-111111111111"},
    )
    assert attr.primary_stage in (AttributionCategory.INFERENCE_USE_LOSS, AttributionCategory.SEMANTIC_DISTORTION)


def test_attribution_supported():
    """Fact was admitted and correctly cited with matching status."""
    fact_id = "00000000-0000-0000-0000-000000000001"
    gold = _make_gold_req(sufficient_sets=[[fact_id]])
    finding = RequirementFinding(
        requirement_id="req_c_plus_plus",
        requirement_text="C++",
        status=FindingStatus.MATCH,
        reason="Demonstrated senior C++ experience",
        candidate_evidence=[
            CandidateEvidenceReference(
                profile_version="v1",
                fact_id=uuid.UUID(fact_id),
            )
        ],
    )
    attr = attribute_requirement_outcome(
        gold_req=gold,
        extracted=True,
        finding=finding,
        strategy=ContextStrategy.JSON,
        admitted_fact_ids={fact_id},
    )
    assert attr.primary_stage == AttributionCategory.SUPPORTED
    assert attr.sufficient_set_admitted is True
    assert attr.sufficient_set_cited is True
