"""Attribution of matching and evidence errors (EVAL-01-S05).

Separates requirement extraction, retrieval coverage, ranking/top-k survival,
context budget packing, inference-time citation use, and semantic distortion.

Attribution Rules:
- A gold fact absent from raw hits is retrieval loss.
- A hit omitted for budget/top-k is packing/ranking loss.
- Admitted evidence unused in final finding is inference-use loss.
- Valid citation with exaggerated meaning is semantic distortion / misuse.
- Expected absence (no documented evidence for GAP/UNKNOWN) is NOT a retrieval failure.
- JSON strategy retrieval metrics are N/A (None).
- Missed requirement extraction is an upstream extraction loss, not retrieval loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from job_automation.contracts.assessment import RequirementCategory, RequirementFinding
from job_automation.contracts.enums import ContextStrategy, FindingStatus
from job_automation.evaluation.labels import FindingAlignmentResult, align_finding_to_gold
from job_automation.evaluation.records import GoldRequirementLabel, ReviewCorrection


class AttributionCategory(str, Enum):
    """Specific failure stage or success state for a requirement."""

    EXTRACTION_LOSS = "extraction_loss"
    RETRIEVAL_LOSS = "retrieval_loss"
    RANKING_LOSS = "ranking_loss"
    BUDGET_PACKING_LOSS = "budget_packing_loss"
    INFERENCE_USE_LOSS = "inference_use_loss"
    SEMANTIC_DISTORTION = "semantic_distortion"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    NO_EVIDENCE_EXPECTED = "no_evidence_expected"
    SUPPORTED = "supported"


@dataclass
class RequirementAttribution:
    """Detailed attribution for a single requirement under an evaluation arm."""

    requirement_id: str
    category: RequirementCategory
    primary_stage: AttributionCategory
    gold_status: FindingStatus
    model_status: FindingStatus | None
    extracted: bool
    gold_fact_ids: list[str]
    retrieved_fact_ids: list[str] | None  # None for JSON
    ranked_fact_ids: list[str] | None     # None if unavailable or JSON
    admitted_fact_ids: list[str]
    cited_fact_ids: list[str]
    sufficient_set_admitted: bool
    sufficient_set_cited: bool
    notes: list[str] = field(default_factory=list)


def attribute_requirement_outcome(
    gold_req: GoldRequirementLabel,
    extracted: bool,
    finding: RequirementFinding | None,
    strategy: ContextStrategy,
    admitted_fact_ids: set[str],
    retrieved_fact_ids: set[str] | None = None,
    ranked_fact_ids: set[str] | None = None,
    reviewer_correction: ReviewCorrection | None = None,
) -> RequirementAttribution:
    """Classify the exact attribution of success or failure for a requirement.

    Follows EVAL-01 attribution hierarchy:
    1. Extraction failure: requirement was not extracted from posting text.
    2. No-evidence expected: gold expectation is GAP/UNKNOWN without candidate facts.
    3. Retrieval loss: gold fact absent from raw retrieved hits (RAG only).
    4. Ranking loss: retrieved in raw hits but pruned by ranking/top-k.
    5. Budget packing loss: survived ranking or in JSON candidate pool, but omitted from admitted prompt.
    6. Inference use loss: admitted into prompt context, but model failed to cite it.
    7. Semantic distortion / unsupported claim: model cited facts but misinterpreted them or made unsupported claim.
    8. Supported: requirement correctly resolved with sufficient evidence.
    """
    notes: list[str] = []

    # 1. Extraction loss
    if not extracted:
        notes.append("Requirement was missing from extracted requirements presented to selector/model")
        return RequirementAttribution(
            requirement_id=gold_req.requirement_id,
            category=gold_req.category,
            primary_stage=AttributionCategory.EXTRACTION_LOSS,
            gold_status=gold_req.gold_status,
            model_status=finding.status if finding else None,
            extracted=False,
            gold_fact_ids=_all_gold_facts(gold_req),
            retrieved_fact_ids=sorted(retrieved_fact_ids) if retrieved_fact_ids is not None else None,
            ranked_fact_ids=sorted(ranked_fact_ids) if ranked_fact_ids is not None else None,
            admitted_fact_ids=sorted(admitted_fact_ids),
            cited_fact_ids=[str(ev.fact_id) for ev in finding.candidate_evidence] if finding else [],
            sufficient_set_admitted=False,
            sufficient_set_cited=False,
            notes=notes,
        )

    alignment = align_finding_to_gold(finding, gold_req, admitted_fact_ids)
    cited_ids = alignment.cited_fact_ids
    cited_set = set(cited_ids)
    gold_facts = _all_gold_facts(gold_req)
    gold_fact_set = set(gold_facts)

    # Check whether any sufficient evidence set was admitted / cited
    sufficient_set_admitted = False
    sufficient_set_cited = alignment.has_sufficient_support

    if gold_req.sufficient_evidence_sets:
        for s_set in gold_req.sufficient_evidence_sets:
            if set(s_set).issubset(admitted_fact_ids):
                sufficient_set_admitted = True
                break
    elif gold_req.gold_status in (FindingStatus.GAP, FindingStatus.UNKNOWN):
        # No evidence needed
        sufficient_set_admitted = True

    # 2. No evidence expected (e.g. unknown skill, genuine gap)
    if gold_req.gold_status in (FindingStatus.GAP, FindingStatus.UNKNOWN) and not gold_facts:
        if alignment.is_unsupported_claim:
            primary_stage = AttributionCategory.UNSUPPORTED_CLAIM
            notes.append("Model claimed MATCH when no candidate evidence exists")
        elif alignment.has_contradiction:
            primary_stage = AttributionCategory.SEMANTIC_DISTORTION
            notes.append("Model cited contradictory facts")
        elif not alignment.status_matches:
            primary_stage = AttributionCategory.SEMANTIC_DISTORTION
            notes.append(f"Model returned {alignment.model_status} instead of expected {gold_req.gold_status}")
        else:
            primary_stage = AttributionCategory.NO_EVIDENCE_EXPECTED
            notes.append("Expected lack of evidence correctly recognized")

        return RequirementAttribution(
            requirement_id=gold_req.requirement_id,
            category=gold_req.category,
            primary_stage=primary_stage,
            gold_status=gold_req.gold_status,
            model_status=alignment.model_status,
            extracted=True,
            gold_fact_ids=[],
            retrieved_fact_ids=sorted(retrieved_fact_ids) if retrieved_fact_ids is not None else None,
            ranked_fact_ids=sorted(ranked_fact_ids) if ranked_fact_ids is not None else None,
            admitted_fact_ids=sorted(admitted_fact_ids),
            cited_fact_ids=cited_ids,
            sufficient_set_admitted=True,
            sufficient_set_cited=alignment.has_sufficient_support,
            notes=notes,
        )

    # For requirements expecting candidate evidence:
    # Check RAG retrieval / ranking stages
    if strategy == ContextStrategy.RAG and retrieved_fact_ids is not None:
        # Check if at least one sufficient set was retrieved
        any_sufficient_retrieved = False
        if gold_req.sufficient_evidence_sets:
            for s_set in gold_req.sufficient_evidence_sets:
                if set(s_set).issubset(retrieved_fact_ids):
                    any_sufficient_retrieved = True
                    break
        else:
            any_sufficient_retrieved = bool(gold_fact_set.intersection(retrieved_fact_ids))

        if not any_sufficient_retrieved:
            notes.append("Required gold evidence facts were not retrieved from the vector index")
            return RequirementAttribution(
                requirement_id=gold_req.requirement_id,
                category=gold_req.category,
                primary_stage=AttributionCategory.RETRIEVAL_LOSS,
                gold_status=gold_req.gold_status,
                model_status=alignment.model_status,
                extracted=True,
                gold_fact_ids=gold_facts,
                retrieved_fact_ids=sorted(retrieved_fact_ids),
                ranked_fact_ids=sorted(ranked_fact_ids) if ranked_fact_ids is not None else None,
                admitted_fact_ids=sorted(admitted_fact_ids),
                cited_fact_ids=cited_ids,
                sufficient_set_admitted=sufficient_set_admitted,
                sufficient_set_cited=sufficient_set_cited,
                notes=notes,
            )

        # Check ranking / top-k pruning
        if ranked_fact_ids is not None:
            any_sufficient_ranked = False
            if gold_req.sufficient_evidence_sets:
                for s_set in gold_req.sufficient_evidence_sets:
                    if set(s_set).issubset(ranked_fact_ids):
                        any_sufficient_ranked = True
                        break
            else:
                any_sufficient_ranked = bool(gold_fact_set.intersection(ranked_fact_ids))

            if not any_sufficient_ranked:
                notes.append("Evidence was retrieved in initial search but dropped during ranking/top-k filtering")
                return RequirementAttribution(
                    requirement_id=gold_req.requirement_id,
                    category=gold_req.category,
                    primary_stage=AttributionCategory.RANKING_LOSS,
                    gold_status=gold_req.gold_status,
                    model_status=alignment.model_status,
                    extracted=True,
                    gold_fact_ids=gold_facts,
                    retrieved_fact_ids=sorted(retrieved_fact_ids),
                    ranked_fact_ids=sorted(ranked_fact_ids),
                    admitted_fact_ids=sorted(admitted_fact_ids),
                    cited_fact_ids=cited_ids,
                    sufficient_set_admitted=sufficient_set_admitted,
                    sufficient_set_cited=sufficient_set_cited,
                    notes=notes,
                )

    # 5. Context budget packing loss: evidence was retrieved/available but omitted from admitted context
    if not sufficient_set_admitted:
        notes.append("Evidence was available in retrieval/profile but omitted from admitted prompt due to context budget")
        return RequirementAttribution(
            requirement_id=gold_req.requirement_id,
            category=gold_req.category,
            primary_stage=AttributionCategory.BUDGET_PACKING_LOSS,
            gold_status=gold_req.gold_status,
            model_status=alignment.model_status,
            extracted=True,
            gold_fact_ids=gold_facts,
            retrieved_fact_ids=sorted(retrieved_fact_ids) if retrieved_fact_ids is not None else None,
            ranked_fact_ids=sorted(ranked_fact_ids) if ranked_fact_ids is not None else None,
            admitted_fact_ids=sorted(admitted_fact_ids),
            cited_fact_ids=cited_ids,
            sufficient_set_admitted=False,
            sufficient_set_cited=sufficient_set_cited,
            notes=notes,
        )

    # 6. Inference use loss: evidence was admitted, but model did not cite sufficient facts
    if not sufficient_set_cited:
        # Did model cite some gold facts or none?
        admitted_and_gold = gold_fact_set.intersection(admitted_fact_ids)
        cited_and_gold = gold_fact_set.intersection(cited_set)

        if not cited_and_gold:
            notes.append("Sufficient evidence was admitted in context, but model failed to cite it")
            primary_stage = AttributionCategory.INFERENCE_USE_LOSS
        elif alignment.has_contradiction:
            notes.append("Model cited contradictory evidence")
            primary_stage = AttributionCategory.SEMANTIC_DISTORTION
        elif alignment.has_unadmitted_or_unknown_citation:
            notes.append("Model cited unadmitted or unknown facts")
            primary_stage = AttributionCategory.UNSUPPORTED_CLAIM
        else:
            notes.append("Model cited partial evidence, but insufficient to establish complete support")
            primary_stage = AttributionCategory.INFERENCE_USE_LOSS

        return RequirementAttribution(
            requirement_id=gold_req.requirement_id,
            category=gold_req.category,
            primary_stage=primary_stage,
            gold_status=gold_req.gold_status,
            model_status=alignment.model_status,
            extracted=True,
            gold_fact_ids=gold_facts,
            retrieved_fact_ids=sorted(retrieved_fact_ids) if retrieved_fact_ids is not None else None,
            ranked_fact_ids=sorted(ranked_fact_ids) if ranked_fact_ids is not None else None,
            admitted_fact_ids=sorted(admitted_fact_ids),
            cited_fact_ids=cited_ids,
            sufficient_set_admitted=True,
            sufficient_set_cited=False,
            notes=notes,
        )

    # 7. Semantic distortion / unsupported claim despite sufficient citations
    if alignment.has_contradiction or not alignment.status_matches:
        notes.append("Model cited sufficient facts but reached incorrect status or contradictory conclusion")
        return RequirementAttribution(
            requirement_id=gold_req.requirement_id,
            category=gold_req.category,
            primary_stage=AttributionCategory.SEMANTIC_DISTORTION,
            gold_status=gold_req.gold_status,
            model_status=alignment.model_status,
            extracted=True,
            gold_fact_ids=gold_facts,
            retrieved_fact_ids=sorted(retrieved_fact_ids) if retrieved_fact_ids is not None else None,
            ranked_fact_ids=sorted(ranked_fact_ids) if ranked_fact_ids is not None else None,
            admitted_fact_ids=sorted(admitted_fact_ids),
            cited_fact_ids=cited_ids,
            sufficient_set_admitted=True,
            sufficient_set_cited=True,
            notes=notes,
        )

    # 8. Supported
    notes.append("Requirement correctly matched with sufficient, admitted evidence")
    return RequirementAttribution(
        requirement_id=gold_req.requirement_id,
        category=gold_req.category,
        primary_stage=AttributionCategory.SUPPORTED,
        gold_status=gold_req.gold_status,
        model_status=alignment.model_status,
        extracted=True,
        gold_fact_ids=gold_facts,
        retrieved_fact_ids=sorted(retrieved_fact_ids) if retrieved_fact_ids is not None else None,
        ranked_fact_ids=sorted(ranked_fact_ids) if ranked_fact_ids is not None else None,
        admitted_fact_ids=sorted(admitted_fact_ids),
        cited_fact_ids=cited_ids,
        sufficient_set_admitted=True,
        sufficient_set_cited=True,
        notes=notes,
    )


def _all_gold_facts(gold_req: GoldRequirementLabel) -> list[str]:
    """Extract unique gold fact IDs across all sufficient evidence sets."""
    facts: list[str] = []
    seen: set[str] = set()
    for s_set in gold_req.sufficient_evidence_sets:
        for fid in s_set:
            if fid not in seen:
                seen.add(fid)
                facts.append(fid)
    return sorted(facts)

