"""Tests for evaluation markdown and text reporting (EVAL-01-S05)."""

import uuid
from job_automation.contracts.enums import ContextStrategy
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.metrics import calculate_evaluation_metrics
from job_automation.evaluation.records import ArmAttempt, ExperimentManifest, PairResult
from job_automation.evaluation.reporting import (
    format_metric_report_markdown,
    format_metric_report_text,
)


def test_reporting_formatting_and_disclaimers():
    """Verify generated report includes all required sections, limitations, and no fake numbers."""
    corpus = EvaluationCorpus.default_synthetic()
    cases = corpus.cases
    exp_id = uuid.uuid4()

    # Generate an end-to-end MetricReport from cases
    manifest = ExperimentManifest(
        experiment_id=exp_id,
        experiment_name="test_report_exp",
        corpus_version="1.0",
        split_name="development",
        case_ids=[c.case_id for c in cases],
        profile_snapshot_hash="hash_p",
        search_policy_fingerprint="fp_pol",
        model_identifier="test-model",
        model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )

    pair_results = []
    for c in cases:
        p_id = uuid.uuid4()
        pair_results.append(
            PairResult(
                experiment_id=exp_id,
                case_id=c.case_id,
                repetition_index=0,
                execution_order=[ContextStrategy.JSON, ContextStrategy.RAG],
                baseline_disposition=c.gold_label.gold_disposition,
                json_arm=ArmAttempt(
                    pair_id=p_id,
                    case_id=c.case_id,
                    strategy=ContextStrategy.JSON,
                    repetition_index=0,
                    execution_status="success",
                ),
                rag_arm=ArmAttempt(
                    pair_id=p_id,
                    case_id=c.case_id,
                    strategy=ContextStrategy.RAG,
                    repetition_index=0,
                    execution_status="success",
                ),
            )
        )

    report = calculate_evaluation_metrics(
        experiment_id=exp_id,
        cases=cases,
        pair_results=pair_results,
    )

    md = format_metric_report_markdown(report, manifest)
    txt = format_metric_report_text(report)

    # Required sections in markdown
    assert "# Evaluation Report:" in md
    assert "## 1. Execution Summary" in md
    assert "## 2. Context Strategy Comparison" in md
    assert "## 3. Matching Decisions (Completed Pairs)" in md
    assert "## 4. Paired Strategy Deltas" in md
    assert "## 5. Requirement Error Attribution Breakdown" in md
    assert "## 6. Sample Limitations & Methodological Constraints" in md
    assert "## 7. Status of Targets" in md
    assert "## 8. Publication Firewall Assurance" in md

    # Check that JSON retrieval is N/A
    assert "| **Retrieval Coverage (Raw)** | N/A |" in md

    # Check that proposed targets are explicitly disclaimed as non-binding benchmarks
    assert "PROPOSED reference benchmarks" in md

    # Check zero-publication assurance
    assert "Zero Salesforce API calls made" in md

    # Check ASCII text output
    assert "EVALUATION REPORT:" in txt
    assert "Retrieval Coverage (Raw)" in txt

