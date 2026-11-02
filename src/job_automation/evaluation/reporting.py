"""Human-readable and structured reporting for evaluation metrics (EVAL-01-S05).

Generates markdown and plain-text evaluation summaries including:
- Controlled experiment metadata.
- Side-by-side strategy metrics (JSON vs RAG).
- 3x3 confusion matrices and error rates.
- Error stage attribution breakdown.
- Paired strategy deltas and agreement.
- Clear separation between empirical observations and PROPOSED targets.
- Explicit sample limitations and zero-publication guarantees.
"""

from __future__ import annotations

import json
from typing import Any

from job_automation.evaluation.records import ExperimentManifest, MetricReport


def format_metric_report_markdown(
    report: MetricReport,
    manifest: ExperimentManifest | None = None,
) -> str:
    """Format a MetricReport into GitHub-flavored Markdown."""
    lines: list[str] = []

    lines.append(f"# Evaluation Report: {report.experiment_id}")
    lines.append("")
    lines.append(f"- **Generated At (UTC)**: {report.generated_at.isoformat()}")
    lines.append(f"- **Metric Spec Version**: `{report.metric_spec_version}`")
    if manifest:
        lines.append(f"- **Experiment Name**: {manifest.experiment_name}")
        lines.append(f"- **Model**: `{manifest.model_identifier}` (`{manifest.model_digest[:16]}...`)")
        lines.append(f"- **Corpus Split**: `{manifest.split_name}`")
        lines.append(f"- **Context Limit**: {manifest.context_limit} tokens")
    lines.append("")

    # 1. Execution Summary
    lines.append("## 1. Execution Summary")
    lines.append("")
    lines.append(f"- **Total Cases Attempted**: {report.total_cases}")
    lines.append(f"- **Completed Pairs (Both Arms Succeeded)**: {report.completed_pairs}")
    lines.append(f"- **Incomplete Pairs**: {report.incomplete_pairs}")
    lines.append(f"- **JSON Arm Completion Rate**: {report.json_arm_completion_rate * 100:.1f}%")
    lines.append(f"- **RAG Arm Completion Rate**: {report.rag_arm_completion_rate * 100:.1f}%")
    lines.append("")

    # 2. Strategy Metrics
    lines.append("## 2. Context Strategy Comparison")
    lines.append("")
    lines.append("| Metric | JSON Context Arm | RAG Context Arm | Proposed Target |")
    lines.append("|---|---|---|---|")

    jm = report.strategy_metrics.get("json", {})
    rm = report.strategy_metrics.get("rag", {})
    pt = report.proposed_targets

    def _fmt_pct(val: float | None) -> str:
        return f"{val * 100:.1f}%" if val is not None else "N/A"

    def _fmt_num(val: float | int | None) -> str:
        return f"{val}" if val is not None else "N/A"

    lines.append(f"| **Retrieval Coverage (Raw)** | N/A | {_fmt_pct(rm.get('retrieval_coverage_raw'))} | {_fmt_pct(pt.get('retrieval_coverage_raw'))} |")
    lines.append(f"| **Retrieval Coverage (Ranked)** | N/A | {_fmt_pct(rm.get('retrieval_coverage_ranked'))} | {_fmt_pct(pt.get('retrieval_coverage_ranked'))} |")
    lines.append(f"| **Admitted Evidence Coverage** | {_fmt_pct(jm.get('admitted_evidence_coverage'))} | {_fmt_pct(rm.get('admitted_evidence_coverage'))} | {_fmt_pct(pt.get('admitted_evidence_coverage'))} |")
    lines.append(f"| **Sufficient Set Hit Rate** | {_fmt_pct(jm.get('sufficient_set_hit_rate'))} | {_fmt_pct(rm.get('sufficient_set_hit_rate'))} | {_fmt_pct(pt.get('sufficient_set_hit_rate'))} |")
    lines.append(f"| **Citation Use Rate** | {_fmt_pct(jm.get('citation_use_rate'))} | {_fmt_pct(rm.get('citation_use_rate'))} | {_fmt_pct(pt.get('citation_use_rate'))} |")
    lines.append(f"| **Semantic Accuracy Rate** | {_fmt_pct(jm.get('semantic_accuracy_rate'))} | {_fmt_pct(rm.get('semantic_accuracy_rate'))} | {_fmt_pct(pt.get('semantic_accuracy_rate'))} |")
    lines.append(f"| **Unsupported Claims Count** | {_fmt_num(jm.get('total_unsupported_claims'))} | {_fmt_num(rm.get('total_unsupported_claims'))} | {_fmt_num(pt.get('unsupported_claims_count'))} |")
    lines.append(f"| **Mean Total Latency (ms)** | {_fmt_num(jm.get('mean_latency_ms'))} | {_fmt_num(rm.get('mean_latency_ms'))} | N/A |")
    lines.append(f"| **Mean Inference Latency (ms)** | {_fmt_num(jm.get('mean_inference_ms'))} | {_fmt_num(rm.get('mean_inference_ms'))} | N/A |")
    lines.append("")

    # 3. Matching Confusion Matrix & Error Rates
    lines.append("## 3. Matching Decisions (Completed Pairs)")
    lines.append("")
    cm = report.confusion_matrices
    for strat in ("json", "rag"):
        s_data = cm.get(strat, {})
        mat = s_data.get("matrix", {})
        lines.append(f"### {strat.upper()} Strategy Confusion Matrix")
        lines.append("")
        lines.append("| Gold \\ Predicted | ELIGIBLE | REVIEW | REJECTED |")
        lines.append("|---|---|---|---|")
        for g_row in ("eligible", "review", "rejected"):
            row = mat.get(g_row, {})
            lines.append(f"| **{g_row.upper()}** | {row.get('eligible', 0)} | {row.get('review', 0)} | {row.get('rejected', 0)} |")
        lines.append("")
        lines.append(f"- **Precision (Eligible)**: {_fmt_pct(s_data.get('precision_eligible'))} (target: {_fmt_pct(pt.get('precision_eligible'))})")
        lines.append(f"- **False Negative Rate (Retention)**: {_fmt_pct(s_data.get('fnr_retention'))} (target: {_fmt_pct(pt.get('fnr_retention'))})")
        lines.append(f"- **FNR (Eligible-only)**: {_fmt_pct(s_data.get('fnr_eligible_only'))}")
        lines.append(f"- **Review Burden**: {_fmt_pct(s_data.get('review_burden'))}")
        lines.append("")

    # 4. Paired Deltas
    lines.append("## 4. Paired Strategy Deltas")
    lines.append("")
    deltas = report.paired_deltas
    lines.append(f"- **Completed Pairs Evaluated**: {deltas.get('completed_pairs_count', 0)}")
    lines.append(f"- **Mean Score Delta (JSON - RAG)**: {_fmt_num(deltas.get('mean_score_delta'))}")
    lines.append(f"- **Median Score Delta (JSON - RAG)**: {_fmt_num(deltas.get('median_score_delta'))}")
    lines.append(f"- **Disposition Agreement Rate**: {_fmt_pct(deltas.get('disposition_agreement_rate'))}")
    lines.append("")

    # 5. Error Attribution Breakdown
    lines.append("## 5. Requirement Error Attribution Breakdown")
    lines.append("")
    lines.append("| Attribution Stage | JSON Arm Count | RAG Arm Count |")
    lines.append("|---|---|---|")
    attr = report.attribution_breakdown
    j_attr = attr.get("json", {})
    r_attr = attr.get("rag", {})
    stages = [
        ("extraction_loss", "Extraction Loss (missed requirement)"),
        ("retrieval_loss", "Retrieval Loss (missing from vector index hits)"),
        ("ranking_loss", "Ranking Loss (pruned by top-k / reranking)"),
        ("budget_packing_loss", "Budget Packing Loss (omitted from prompt context)"),
        ("inference_use_loss", "Inference Use Loss (admitted but unused by model)"),
        ("semantic_distortion", "Semantic Distortion / Contradiction"),
        ("unsupported_claim", "Unsupported Claim / Unadmitted Citation"),
        ("no_evidence_expected", "No Evidence Expected (correct gap/unknown)"),
        ("supported", "Supported (sufficient admitted evidence cited)"),
    ]
    for key, label in stages:
        lines.append(f"| {label} | {j_attr.get(key, 0)} | {r_attr.get(key, 0)} |")
    lines.append("")

    # 6. Sample Limitations
    lines.append("## 6. Sample Limitations & Methodological Constraints")
    lines.append("")
    for lim in report.sample_limitations:
        lines.append(f"- {lim}")
    lines.append("")

    # 7. Proposed Targets Note
    lines.append("## 7. Status of Targets")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> The targets shown in Section 2 are **PROPOSED reference benchmarks** from `settings.py`.")
    lines.append("> They are not achieved empirical measurements and do not automatically alter production thresholds.")
    lines.append("")

    # 8. Publication Firewall Assurance
    lines.append("## 8. Publication Firewall Assurance")
    lines.append("")
    lines.append("- Zero Salesforce API calls made.")
    lines.append("- Zero writes to production `canonical_jobs`, `assessments`, or `sync_operations` tables.")
    lines.append("- Dedicated isolated SQLite database used for all evaluation artifacts.")
    lines.append("")

    return "\n".join(lines)


def format_metric_report_text(report: MetricReport) -> str:
    """Format a MetricReport into concise CLI ASCII text."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"EVALUATION REPORT: {report.experiment_id}")
    lines.append(f"Metric Spec: {report.metric_spec_version} | Completed Pairs: {report.completed_pairs}/{report.total_cases}")
    lines.append("=" * 70)

    jm = report.strategy_metrics.get("json", {})
    rm = report.strategy_metrics.get("rag", {})

    def _fmt(val: float | None) -> str:
        return f"{val * 100:.1f}%" if val is not None else "N/A"

    lines.append(f"{'Metric':<35} | {'JSON':<12} | {'RAG':<12}")
    lines.append("-" * 70)
    lines.append(f"{'Completion Rate':<35} | {_fmt(report.json_arm_completion_rate):<12} | {_fmt(report.rag_arm_completion_rate):<12}")
    lines.append(f"{'Retrieval Coverage (Raw)':<35} | {'N/A':<12} | {_fmt(rm.get('retrieval_coverage_raw')):<12}")
    lines.append(f"{'Admitted Evidence Coverage':<35} | {_fmt(jm.get('admitted_evidence_coverage')):<12} | {_fmt(rm.get('admitted_evidence_coverage')):<12}")
    lines.append(f"{'Sufficient Set Hit Rate':<35} | {_fmt(jm.get('sufficient_set_hit_rate')):<12} | {_fmt(rm.get('sufficient_set_hit_rate')):<12}")
    lines.append(f"{'Citation Use Rate':<35} | {_fmt(jm.get('citation_use_rate')):<12} | {_fmt(rm.get('citation_use_rate')):<12}")
    lines.append(f"{'Semantic Accuracy Rate':<35} | {_fmt(jm.get('semantic_accuracy_rate')):<12} | {_fmt(rm.get('semantic_accuracy_rate')):<12}")
    lines.append(f"{'Unsupported Claims':<35} | {str(jm.get('total_unsupported_claims')):<12} | {str(rm.get('total_unsupported_claims')):<12}")

    deltas = report.paired_deltas
    lines.append("-" * 70)
    lines.append(f"Mean Score Delta (JSON - RAG): {deltas.get('mean_score_delta')}")
    lines.append(f"Disposition Agreement Rate: {_fmt(deltas.get('disposition_agreement_rate'))}")
    lines.append("=" * 70)
    return "\n".join(lines)

