"""End-to-end integration tests for EVAL-01 paired evaluation workflow."""

import json
from pathlib import Path
import sqlite3
import uuid
import pytest

from job_automation.assessment.llm_records import AssessmentRunResult
from job_automation.assessment.service import AssessmentService
from job_automation.contracts.assessment import Assessment, LLMAssessmentMetadata
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    FindingStatus,
)
from job_automation.contracts.interfaces import AssessorV2
from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.metrics import calculate_evaluation_metrics
from job_automation.evaluation.population_reader import read_rejected_population
from job_automation.evaluation.records import ExperimentManifest
from job_automation.evaluation.reporting import (
    format_metric_report_markdown,
    format_metric_report_text,
)
from job_automation.evaluation.review_export import export_review_packets
from job_automation.evaluation.review_import import import_review_corrections
from job_automation.evaluation.runner import EvaluationRunner
from job_automation.evaluation.sampling import sample_rejected_population
from job_automation.evaluation.settings import EvaluationSettings


class ScriptedEvaluationAssessor(AssessorV2):
    """Deterministic assessor for whole-workflow evaluation integration."""

    def assess(self, request):
        canonical_id = request.canonical_job_id
        strategy = request.context_strategy

        # Scripted disposition matching deterministic baseline
        disp = request.deterministic_baseline.final_disposition
        score = 85.0 if disp == AssessmentDisposition.ELIGIBLE else (60.0 if disp == AssessmentDisposition.REVIEW else 25.0)

        asmt = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=canonical_id,
            posting_revision=request.posting_revision,
            profile_version=request.profile.profile_version,
            policy_version=request.policy.policy_version,
            assessment_method=AssessmentMethod.LLM,
            final_disposition=disp,
            relevance_decision=disp,
            relevance_score=score,
            score_scale="0-100",
            summary_reason=f"Scripted eval assessment for {strategy.value}",
            model_metadata=LLMAssessmentMetadata(
                model_identifier="scripted-local-model",
                prompt_version="v1",
                context_strategy=strategy,
            ),
            rule_outcomes=request.deterministic_baseline.rule_outcomes,
            requirement_findings=[],
        )

        return AssessmentRunResult(
            status="success",
            assessment=asmt,
            input_fingerprint=f"fp_{strategy.value}_{canonical_id}",
        )


def test_full_evaluation_workflow_integration(tmp_path: Path):
    """Execute complete EVAL-01 lifecycle: run, metrics, review export/import, sampling, zero-pub check."""
    eval_dir = (tmp_path / "Full_Workflow_Eval").resolve()
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Sentinel production database to guarantee absolute zero production contamination
    prod_db = (tmp_path / "Production_Sentinel.db").resolve()
    conn = sqlite3.connect(prod_db)
    conn.execute("CREATE TABLE canonical_jobs (id TEXT PRIMARY KEY, title TEXT);")
    conn.execute("CREATE TABLE assessments (id TEXT PRIMARY KEY, disposition TEXT);")
    conn.execute("CREATE TABLE sync_operations (id TEXT PRIMARY KEY, status TEXT);")
    conn.commit()
    conn.close()

    settings = EvaluationSettings(
        eval_root=str(eval_dir),
        production_db_path=str(prod_db),
    )
    env = create_evaluation_environment(settings)

    try:
        corpus = EvaluationCorpus.default_synthetic()
        cases = corpus.cases
        case_ids = [c.case_id for c in cases]

        manifest = ExperimentManifest(
            experiment_name="integration_full_experiment",
            corpus_version="1.0",
            split_name="all",
            case_ids=case_ids,
            profile_snapshot_hash="hash_p",
            search_policy_fingerprint="fp_pol",
            model_identifier="scripted-local-model",
            model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            repetitions_per_pair=1,
        )

        # 1. Run paired evaluation
        asmt_service = AssessmentService()
        assessor = ScriptedEvaluationAssessor()
        runner = EvaluationRunner(
            environment=env,
            assessment_service=asmt_service,
            llm_assessor=assessor,
        )

        pair_results = runner.run_experiment(manifest, corpus)
        assert len(pair_results) == len(cases)
        assert all(p.pair_completed for p in pair_results)

        # 2. Calculate honest metrics & format report
        report = calculate_evaluation_metrics(
            experiment_id=manifest.experiment_id,
            cases=cases,
            pair_results=pair_results,
        )
        assert report.total_cases == len(cases)
        assert report.completed_pairs == len(cases)
        assert report.incomplete_pairs == 0
        assert report.json_arm_completion_rate == 1.0
        assert report.rag_arm_completion_rate == 1.0

        md_report = format_metric_report_markdown(report, manifest)
        txt_report = format_metric_report_text(report)
        assert "EVALUATION REPORT:" in txt_report
        assert "## 2. Context Strategy Comparison" in md_report

        # 3. Export review packets
        packets_file = eval_dir / "review_packets.json"
        export_review_packets(cases, pair_results, packets_file)
        assert packets_file.exists()

        # 4. Import a valid correction
        c0 = cases[0]
        valid_fact = str(c0.profile.evidence_records[0].fact_id)
        corrections = [
            {
                "case_id": c0.case_id,
                "reviewer_id": "adjudicator_bob",
                "target_type": "model_finding",
                "old_value": {"status": "match"},
                "new_value": {"status": "match"},
                "reason": "Confirmed match seniority",
                "supporting_evidence": [
                    {
                        "source_kind": "candidate",
                        "profile_version": c0.profile.profile_version,
                        "fact_id": valid_fact,
                    }
                ],
                "active_review_seconds": 25.0,
                "adjudication_status": "adjudicated",
            }
        ]
        imported = import_review_corrections(corrections, env.repository, c0.profile, c0.policy)
        assert len(imported) == 1

        # 5. Stratified sampling on rejected assessments
        # Extract rejected cases from results for sampling
        sample_pop = read_rejected_population(
            records=[
                {
                    "canonical_job_id": p.rag_arm.final_assessment.canonical_job_id,
                    "posting_revision": p.rag_arm.final_assessment.posting_revision,
                    "title": "Posting Title",
                    "final_disposition": p.rag_arm.final_assessment.final_disposition.value,
                    "summary_reason": p.rag_arm.final_assessment.summary_reason,
                }
                for p in pair_results
                if p.rag_arm.final_assessment.final_disposition == AssessmentDisposition.REJECTED
            ],
            cohort_id="cohort_integration",
        )
        sample_manifest = sample_rejected_population(sample_pop, target_sample_size=3, seed=42)
        assert sample_manifest.sample_size <= len(sample_pop.eligible_candidates)
        env.repository.save_sample_manifest(sample_manifest)

        # 6. Verify zero publication isolation: production sentinel DB is completely untouched
        conn = sqlite3.connect(prod_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM canonical_jobs;")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM assessments;")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM sync_operations;")
        assert cursor.fetchone()[0] == 0
        conn.close()

    finally:
        env.close()

