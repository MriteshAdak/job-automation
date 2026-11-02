"""Observability and intermediate trace capture for evaluation arms (EVAL-01-S04).

Enforces:
- Capture of C09 context bundle summary.
- Capture of RAG retrieval trace (raw hits, fused candidates, admitted, omitted).
- Model proposal, validation issues, and final C11 record capture.
"""

from __future__ import annotations

from typing import Any

from job_automation.assessment.llm_records import (
    AssessmentProposal,
    AssessmentRunResult,
)
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ValidationIssue


def extract_arm_trace_data(
    run_result: AssessmentRunResult | None,
    context_bundle: ContextBundle | None = None,
    retrieval_trace: Any | None = None,
) -> dict[str, Any]:
    """Capture intermediate stage observables into a structured dictionary."""
    trace: dict[str, Any] = {
        "has_bundle": context_bundle is not None,
        "admitted_fact_ids": [],
        "omitted_fact_ids": [],
        "raw_hit_fact_ids": [],
        "ranked_candidate_fact_ids": [],
        "mandatory_fact_ids": [],
        "final_cited_fact_ids": [],
    }

    if context_bundle is not None:
        trace["admitted_fact_ids"] = [
            str(f.fact_id) for f in getattr(context_bundle, "admitted_facts", [])
        ]
        trace["omitted_fact_ids"] = [
            str(f.fact_id) for f in getattr(context_bundle, "omitted_facts", [])
        ]
        trace["strategy"] = getattr(context_bundle.strategy, "value", str(context_bundle.strategy))

    if retrieval_trace is not None:
        trace["raw_hit_fact_ids"] = [
            str(hit.fact_id) for hit in getattr(retrieval_trace, "raw_hits", [])
        ]
        trace["ranked_candidate_fact_ids"] = [
            str(cand.fact_id) for cand in getattr(retrieval_trace, "fused_candidates", [])
        ]
        trace["mandatory_fact_ids"] = [
            str(fid) for fid in getattr(retrieval_trace, "mandatory_fact_ids", [])
        ]

    if run_result is not None and run_result.assessment is not None:
        asmt = run_result.assessment
        cited: set[str] = set()
        for f in asmt.requirement_findings:
            for ev in f.candidate_evidence:
                cited.add(str(ev.fact_id))
        trace["final_cited_fact_ids"] = sorted(cited)

    return trace

