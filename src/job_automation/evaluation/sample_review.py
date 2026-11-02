"""Audit review metrics for sampled rejected jobs (EVAL-01-S07).

Enforces:
- Strict metric nomenclature: False Omission Proportion among Rejects (never population FNR).
- Explicit unreviewed counts and nonresponse handling (never silently drop unreviewed).
- Distinguishes evaluator factual defects from policy preference disagreements.
- Stratum-level denominators and weighted false omission estimation.
"""

from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import AssessmentDisposition
from job_automation.evaluation.metrics import safe_div
from job_automation.evaluation.records import SampleManifest


class SampleReviewItem(ContractModel):
    """Audit review outcome for a single sampled rejected job."""

    canonical_job_id: str
    stratum: str
    reviewed: bool = False
    gold_disposition: AssessmentDisposition | None = None
    defect_type: Literal[
        "evaluator_defect",
        "policy_preference_disagreement",
        "correct_rejection",
        "unreviewed",
    ] = "unreviewed"
    notes: str | None = None


class SampleAuditReport(ContractModel):
    """Audit report for rejected job false omissions."""

    cohort_id: str
    total_sampled: int
    total_reviewed: int
    unreviewed_count: int
    review_coverage_rate: float | None
    false_omissions_count: int
    false_omission_proportion_among_rejects: float | None = Field(
        description="Proportion of reviewed rejected jobs that should have been ELIGIBLE or REVIEW. STRICTLY not population FNR.",
    )
    stratum_breakdown: dict[str, Any]
    population_weighted_estimate: float | None = None
    metric_limitation_note: str = Field(
        default="Reject-only sampling measures false omission proportion among rejects, NOT overall population recall or FNR.",
    )


def audit_sampled_rejects(
    manifest: SampleManifest,
    reviews: Sequence[SampleReviewItem],
) -> SampleAuditReport:
    """Compute false-omission metrics across sampled rejected jobs."""
    total_sampled = manifest.sample_size
    review_map = {r.canonical_job_id: r for r in reviews}

    total_reviewed = 0
    unreviewed_count = 0
    false_omissions_count = 0

    stratum_stats: dict[str, dict[str, int]] = {}
    for cat in manifest.stratification_summary:
        stratum_stats[cat] = {"sampled": 0, "reviewed": 0, "false_omissions": 0}

    for jid in manifest.selected_case_ids:
        r = review_map.get(jid)
        stratum = r.stratum if r else "unknown"
        if stratum not in stratum_stats:
            stratum_stats[stratum] = {"sampled": 0, "reviewed": 0, "false_omissions": 0}
        stratum_stats[stratum]["sampled"] += 1

        if r is None or not r.reviewed or r.defect_type == "unreviewed":
            unreviewed_count += 1
            continue

        total_reviewed += 1
        stratum_stats[stratum]["reviewed"] += 1

        # False omission: gold adjudication is ELIGIBLE or REVIEW
        if r.gold_disposition in (AssessmentDisposition.ELIGIBLE, AssessmentDisposition.REVIEW):
            false_omissions_count += 1
            stratum_stats[stratum]["false_omissions"] += 1

    coverage_rate = safe_div(total_reviewed, total_sampled)
    fo_proportion = safe_div(false_omissions_count, total_reviewed)

    # Stratum-level breakdown
    stratum_breakdown: dict[str, Any] = {}
    weighted_fo_sum = 0.0
    total_weight = 0.0

    for cat, s in stratum_stats.items():
        n_rev = s["reviewed"]
        n_fo = s["false_omissions"]
        cat_rate = safe_div(n_fo, n_rev)
        stratum_breakdown[cat] = {
            "population_size": manifest.stratification_summary.get(cat, s["sampled"]),
            "sampled": s["sampled"],
            "reviewed": n_rev,
            "false_omissions": n_fo,
            "false_omission_rate": cat_rate,
        }

        # Weighting by stratum population size
        pop_n = manifest.stratification_summary.get(cat, 0)
        if cat_rate is not None and pop_n > 0:
            weighted_fo_sum += cat_rate * pop_n
            total_weight += pop_n

    weighted_est = safe_div(weighted_fo_sum, total_weight) if total_weight > 0 else None

    return SampleAuditReport(
        cohort_id=manifest.population_cohort_id,
        total_sampled=total_sampled,
        total_reviewed=total_reviewed,
        unreviewed_count=unreviewed_count,
        review_coverage_rate=coverage_rate,
        false_omissions_count=false_omissions_count,
        false_omission_proportion_among_rejects=fo_proportion,
        stratum_breakdown=stratum_breakdown,
        population_weighted_estimate=weighted_est,
    )

