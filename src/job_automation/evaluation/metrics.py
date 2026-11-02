"""Metrics calculation for paired evaluation (EVAL-01-S05).

Calculates honest, reproducible metrics comparing JSON and RAG strategies:
- Retrieval coverage (|G_r ∩ H_r| / |G_r|) and post-ranking coverage (|G_r ∩ K_r| / |G_r|).
  JSON retrieval metrics are strictly None ("N/A").
- Admitted evidence coverage (|G_r ∩ A| / |G_r|) and sufficient evidence set hit rate.
- Citation use (|G_r ∩ A ∩ U_r| / |G_r ∩ A|) and semantic accuracy.
- Matching error confusion matrices (Eligible/Review/Rejected) on completed pairs only.
  False negative rate (FNR), eligible precision, review burden.
- Paired strategy score deltas and disposition agreement.
- Attribution breakdown (extraction, retrieval, ranking, packing, inference, semantic).
- Strict zero-denominator rules: 0/0 returns None (never fabricated 1.0 or 0.0).
- Explicit sample limitations and separate proposed targets.
"""

from __future__ import annotations

import statistics
import uuid
from typing import Any, Sequence

from job_automation.contracts.assessment import Assessment, RequirementCategory
from job_automation.contracts.enums import AssessmentDisposition, ContextStrategy, FindingStatus
from job_automation.evaluation.attribution import (
    AttributionCategory,
    RequirementAttribution,
    attribute_requirement_outcome,
)
from job_automation.evaluation.records import (
    ArmAttempt,
    EvaluationCase,
    GoldRequirementLabel,
    MetricReport,
    PairResult,
    ReviewCorrection,
)
from job_automation.evaluation.settings import METRIC_SPEC_VERSION, PROPOSED_TARGETS


def safe_div(numerator: int | float, denominator: int | float) -> float | None:
    """Safely divide two numbers, returning None if denominator is zero."""
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def calculate_arm_metrics(
    arm: ArmAttempt,
    gold_requirements: list[GoldRequirementLabel],
    reviewer_corrections: list[ReviewCorrection] | None = None,
) -> dict[str, Any]:
    """Calculate requirement-level metrics and attribution for a single arm attempt."""
    if arm.execution_status != "success" or arm.final_assessment is None:
        return {
            "execution_status": arm.execution_status,
            "completed": False,
            "retrieval_coverage_raw": None,
            "retrieval_coverage_ranked": None,
            "admitted_evidence_coverage": None,
            "sufficient_set_hit_rate": None,
            "citation_use_rate": None,
            "semantic_accuracy_rate": None,
            "unsupported_claims_count": 0,
            "attributions": [],
            "attribution_counts": {cat.value: 0 for cat in AttributionCategory},
        }

    asmt = arm.final_assessment
    strategy = arm.strategy
    trace = arm.captured_trace or {}

    admitted_facts = set(trace.get("admitted_fact_ids", []))
    retrieved_facts = set(trace.get("raw_retrieved_fact_ids", [])) if strategy == ContextStrategy.RAG else None
    ranked_facts = set(trace.get("ranked_fact_ids", [])) if strategy == ContextStrategy.RAG and "ranked_fact_ids" in trace else None

    # Map model findings by requirement_id
    model_findings = {f.requirement_id: f for f in asmt.requirement_findings}

    attributions: list[RequirementAttribution] = []
    attribution_counts = {cat.value: 0 for cat in AttributionCategory}

    # Tracking counters
    gold_facts_total = 0
    raw_retrieved_gold_total = 0
    ranked_gold_total = 0
    admitted_gold_total = 0
    admitted_and_gold_total = 0
    cited_admitted_gold_total = 0

    sufficient_sets_possible = 0
    sufficient_sets_admitted = 0
    evaluable_requirements = len(gold_requirements)
    sufficient_semantic_support_count = 0
    unsupported_claims_count = 0

    for gold_req in gold_requirements:
        finding = model_findings.get(gold_req.requirement_id)
        extracted = (finding is not None) or (gold_req.requirement_id in trace.get("extracted_requirement_ids", []))

        attr = attribute_requirement_outcome(
            gold_req=gold_req,
            extracted=extracted,
            finding=finding,
            strategy=strategy,
            admitted_fact_ids=admitted_facts,
            retrieved_fact_ids=retrieved_facts,
            ranked_fact_ids=ranked_facts,
        )
        attributions.append(attr)
        attribution_counts[attr.primary_stage.value] += 1

        # Gold facts for this requirement
        g_facts = set(attr.gold_fact_ids)
        if g_facts:
            gold_facts_total += len(g_facts)
            if retrieved_facts is not None:
                raw_retrieved_gold_total += len(g_facts.intersection(retrieved_facts))
            if ranked_facts is not None:
                ranked_gold_total += len(g_facts.intersection(ranked_facts))
            
            admitted_intersect = g_facts.intersection(admitted_facts)
            admitted_gold_total += len(admitted_intersect)

            if admitted_intersect:
                admitted_and_gold_total += len(admitted_intersect)
                cited_admitted_gold_total += len(admitted_intersect.intersection(attr.cited_fact_ids))

        if gold_req.sufficient_evidence_sets:
            sufficient_sets_possible += 1
            if attr.sufficient_set_admitted:
                sufficient_sets_admitted += 1

        if attr.primary_stage == AttributionCategory.SUPPORTED or attr.primary_stage == AttributionCategory.NO_EVIDENCE_EXPECTED:
            sufficient_semantic_support_count += 1

        if attr.primary_stage == AttributionCategory.UNSUPPORTED_CLAIM:
            unsupported_claims_count += 1

    # Safe divisions
    raw_retrieval_coverage = (
        safe_div(raw_retrieved_gold_total, gold_facts_total)
        if strategy == ContextStrategy.RAG
        else None  # JSON retrieval is strictly N/A
    )
    ranked_retrieval_coverage = (
        safe_div(ranked_gold_total, gold_facts_total)
        if (strategy == ContextStrategy.RAG and ranked_facts is not None)
        else None
    )
    admitted_coverage = safe_div(admitted_gold_total, gold_facts_total)
    sufficient_set_hit_rate = safe_div(sufficient_sets_admitted, sufficient_sets_possible)
    citation_use_rate = safe_div(cited_admitted_gold_total, admitted_and_gold_total)
    semantic_accuracy_rate = safe_div(sufficient_semantic_support_count, evaluable_requirements)

    return {
        "execution_status": arm.execution_status,
        "completed": True,
        "retrieval_coverage_raw": raw_retrieval_coverage,
        "retrieval_coverage_ranked": ranked_retrieval_coverage,
        "admitted_evidence_coverage": admitted_coverage,
        "sufficient_set_hit_rate": sufficient_set_hit_rate,
        "citation_use_rate": citation_use_rate,
        "semantic_accuracy_rate": semantic_accuracy_rate,
        "unsupported_claims_count": unsupported_claims_count,
        "gold_facts_count": gold_facts_total,
        "raw_retrieved_gold_count": raw_retrieved_gold_total if strategy == ContextStrategy.RAG else None,
        "admitted_gold_count": admitted_gold_total,
        "cited_admitted_gold_count": cited_admitted_gold_total,
        "attributions": attributions,
        "attribution_counts": attribution_counts,
        "latency_ms": {
            "total": arm.stage_latencies_ms.get("total_ms"),
            "context_selection": arm.stage_latencies_ms.get("context_selection_ms"),
            "inference": arm.stage_latencies_ms.get("inference_ms"),
        },
        "token_usage": arm.token_counts or {},
    }


def calculate_confusion_matrix(
    completed_pairs: Sequence[PairResult],
    cases: dict[str, EvaluationCase],
) -> dict[str, Any]:
    """Compute 3x3 confusion matrix and error rates on completed pairs.

    Classes: ELIGIBLE, REVIEW, REJECTED.
    Retention positive detection:
    - Gold positive = ELIGIBLE or REVIEW
    - False Negative (FN) = predicted REJECTED when gold was ELIGIBLE or REVIEW
    - FNR = FN / gold_positives
    - Precision (Eligible) = gold ELIGIBLE / predicted ELIGIBLE
    """
    labels = [
        AssessmentDisposition.ELIGIBLE.value,
        AssessmentDisposition.REVIEW.value,
        AssessmentDisposition.REJECTED.value,
    ]

    matrices = {
        "json": {g: {p: 0 for p in labels} for g in labels},
        "rag": {g: {p: 0 for p in labels} for g in labels},
    }

    stats = {
        "json": {"total": 0, "gold_positives": 0, "predicted_positives": 0, "fn": 0, "gold_eligible": 0, "pred_eligible": 0, "tp_eligible": 0, "fp_eligible": 0, "pred_review": 0},
        "rag": {"total": 0, "gold_positives": 0, "predicted_positives": 0, "fn": 0, "gold_eligible": 0, "pred_eligible": 0, "tp_eligible": 0, "fp_eligible": 0, "pred_review": 0},
    }

    for pair in completed_pairs:
        if not pair.pair_completed:
            continue

        case = cases.get(pair.case_id)
        if case is None:
            continue

        gold_disp = case.gold_label.gold_disposition.value
        if gold_disp not in labels:
            continue

        for strat_name, arm in [("json", pair.json_arm), ("rag", pair.rag_arm)]:
            if arm.final_assessment is None:
                continue
            pred_disp = arm.final_assessment.final_disposition.value
            if pred_disp not in labels:
                continue

            matrices[strat_name][gold_disp][pred_disp] += 1
            s = stats[strat_name]
            s["total"] += 1

            is_gold_pos = gold_disp in (AssessmentDisposition.ELIGIBLE.value, AssessmentDisposition.REVIEW.value)
            is_pred_pos = pred_disp in (AssessmentDisposition.ELIGIBLE.value, AssessmentDisposition.REVIEW.value)

            if is_gold_pos:
                s["gold_positives"] += 1
                if pred_disp == AssessmentDisposition.REJECTED.value:
                    s["fn"] += 1

            if is_pred_pos:
                s["predicted_positives"] += 1

            if gold_disp == AssessmentDisposition.ELIGIBLE.value:
                s["gold_eligible"] += 1

            if pred_disp == AssessmentDisposition.ELIGIBLE.value:
                s["pred_eligible"] += 1
                if gold_disp == AssessmentDisposition.ELIGIBLE.value:
                    s["tp_eligible"] += 1
                elif gold_disp == AssessmentDisposition.REJECTED.value:
                    s["fp_eligible"] += 1

            if pred_disp == AssessmentDisposition.REVIEW.value:
                s["pred_review"] += 1

    result: dict[str, Any] = {}
    for strat in ("json", "rag"):
        s = stats[strat]
        fnr = safe_div(s["fn"], s["gold_positives"])
        prec_eligible = safe_div(s["tp_eligible"], s["pred_eligible"])
        review_burden = safe_div(s["pred_review"], s["total"])
        eligible_fn = s["gold_eligible"] - s["tp_eligible"]
        eligible_only_fnr = safe_div(eligible_fn, s["gold_eligible"])

        result[strat] = {
            "matrix": matrices[strat],
            "total_evaluated": s["total"],
            "gold_positives": s["gold_positives"],
            "false_negatives": s["fn"],
            "fnr_retention": fnr,
            "gold_eligible_count": s["gold_eligible"],
            "predicted_eligible_count": s["pred_eligible"],
            "precision_eligible": prec_eligible,
            "false_positives_eligible": s["fp_eligible"],
            "fnr_eligible_only": eligible_only_fnr,
            "review_burden": review_burden,
        }

    return result


def calculate_strategy_deltas(completed_pairs: Sequence[PairResult]) -> dict[str, Any]:
    """Calculate paired score deltas and disposition agreement on completed pairs."""
    valid_pairs = [p for p in completed_pairs if p.pair_completed]
    total_valid = len(valid_pairs)

    if total_valid == 0:
        return {
            "completed_pairs_count": 0,
            "mean_score_delta": None,
            "median_score_delta": None,
            "disposition_agreements_count": 0,
            "disposition_agreement_rate": None,
        }

    deltas: list[float] = []
    agreements = 0

    for pair in valid_pairs:
        if pair.strategy_delta_score is not None:
            deltas.append(pair.strategy_delta_score)
        if pair.disposition_agreement is True:
            agreements += 1

    mean_delta = round(statistics.mean(deltas), 2) if deltas else None
    median_delta = round(statistics.median(deltas), 2) if deltas else None
    agreement_rate = safe_div(agreements, total_valid)

    return {
        "completed_pairs_count": total_valid,
        "mean_score_delta": mean_delta,
        "median_score_delta": median_delta,
        "score_deltas": deltas,
        "disposition_agreements_count": agreements,
        "disposition_agreement_rate": agreement_rate,
    }


def calculate_evaluation_metrics(
    experiment_id: uuid.UUID,
    cases: Sequence[EvaluationCase],
    pair_results: Sequence[PairResult],
    reviewer_corrections: list[ReviewCorrection] | None = None,
) -> MetricReport:
    """Aggregate individual arm metrics, confusion matrices, and deltas into a MetricReport."""
    case_map = {c.case_id: c for c in cases}
    total_cases = len(cases)

    json_successes = sum(1 for p in pair_results if p.json_arm.execution_status == "success")
    rag_successes = sum(1 for p in pair_results if p.rag_arm.execution_status == "success")
    completed_pairs = sum(1 for p in pair_results if p.pair_completed)
    incomplete_pairs = len(pair_results) - completed_pairs

    json_completion_rate = safe_div(json_successes, total_cases) or 0.0
    rag_completion_rate = safe_div(rag_successes, total_cases) or 0.0

    # Aggregate arm metrics
    json_arm_metrics_list = []
    rag_arm_metrics_list = []

    total_attributions = {
        "json": {cat.value: 0 for cat in AttributionCategory},
        "rag": {cat.value: 0 for cat in AttributionCategory},
    }

    for p in pair_results:
        case = case_map.get(p.case_id)
        if not case:
            continue

        jm = calculate_arm_metrics(p.json_arm, case.gold_label.requirements, reviewer_corrections)
        rm = calculate_arm_metrics(p.rag_arm, case.gold_label.requirements, reviewer_corrections)

        json_arm_metrics_list.append(jm)
        rag_arm_metrics_list.append(rm)

        for cat_val, count in jm["attribution_counts"].items():
            total_attributions["json"][cat_val] += count
        for cat_val, count in rm["attribution_counts"].items():
            total_attributions["rag"][cat_val] += count

    # Compute macro averages across completed arms
    def _avg(vals: list[float | None]) -> float | None:
        clean = [v for v in vals if v is not None]
        return round(statistics.mean(clean), 4) if clean else None

    strategy_metrics = {
        "json": {
            "completion_rate": json_completion_rate,
            "retrieval_coverage_raw": None,  # JSON is strictly N/A
            "retrieval_coverage_ranked": None,
            "admitted_evidence_coverage": _avg([m["admitted_evidence_coverage"] for m in json_arm_metrics_list if m["completed"]]),
            "sufficient_set_hit_rate": _avg([m["sufficient_set_hit_rate"] for m in json_arm_metrics_list if m["completed"]]),
            "citation_use_rate": _avg([m["citation_use_rate"] for m in json_arm_metrics_list if m["completed"]]),
            "semantic_accuracy_rate": _avg([m["semantic_accuracy_rate"] for m in json_arm_metrics_list if m["completed"]]),
            "total_unsupported_claims": sum(m["unsupported_claims_count"] for m in json_arm_metrics_list),
            "mean_latency_ms": _avg([m["latency_ms"]["total"] for m in json_arm_metrics_list if m["completed"]]),
            "mean_inference_ms": _avg([m["latency_ms"]["inference"] for m in json_arm_metrics_list if m["completed"]]),
        },
        "rag": {
            "completion_rate": rag_completion_rate,
            "retrieval_coverage_raw": _avg([m["retrieval_coverage_raw"] for m in rag_arm_metrics_list if m["completed"]]),
            "retrieval_coverage_ranked": _avg([m["retrieval_coverage_ranked"] for m in rag_arm_metrics_list if m["completed"]]),
            "admitted_evidence_coverage": _avg([m["admitted_evidence_coverage"] for m in rag_arm_metrics_list if m["completed"]]),
            "sufficient_set_hit_rate": _avg([m["sufficient_set_hit_rate"] for m in rag_arm_metrics_list if m["completed"]]),
            "citation_use_rate": _avg([m["citation_use_rate"] for m in rag_arm_metrics_list if m["completed"]]),
            "semantic_accuracy_rate": _avg([m["semantic_accuracy_rate"] for m in rag_arm_metrics_list if m["completed"]]),
            "total_unsupported_claims": sum(m["unsupported_claims_count"] for m in rag_arm_metrics_list),
            "mean_latency_ms": _avg([m["latency_ms"]["total"] for m in rag_arm_metrics_list if m["completed"]]),
            "mean_inference_ms": _avg([m["latency_ms"]["inference"] for m in rag_arm_metrics_list if m["completed"]]),
        },
    }

    confusion = calculate_confusion_matrix(pair_results, case_map)
    deltas = calculate_strategy_deltas(pair_results)

    sample_limitations = [
        "Synthetic non-sensitive corpus (8 canonical test cases); not a random sample of the German job market.",
        "Proposed targets are non-binding reference guidelines and must not be treated as production acceptance criteria.",
        "Evaluations performed in offline isolated workspace; Salesforce publication completely firewalled.",
        "Reject-only sample measures false-omission proportion among rejects, not population FNR.",
    ]

    return MetricReport(
        experiment_id=experiment_id,
        metric_spec_version=METRIC_SPEC_VERSION,
        total_cases=total_cases,
        completed_pairs=completed_pairs,
        incomplete_pairs=incomplete_pairs,
        json_arm_completion_rate=json_completion_rate,
        rag_arm_completion_rate=rag_completion_rate,
        strategy_metrics=strategy_metrics,
        paired_deltas=deltas,
        confusion_matrices=confusion,
        attribution_breakdown=total_attributions,
        sample_limitations=sample_limitations,
        proposed_targets=PROPOSED_TARGETS,
    )
