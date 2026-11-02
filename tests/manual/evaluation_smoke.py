"""Manual smoke test script for EVAL-01 paired evaluation harness.

Runs a quick offline validation of:
- Evaluation environment initialization.
- Dependency gate register status.
- Paired evaluation run on canonical synthetic cases.
- Honest metric report generation.
- Zero-publication firewall verification.

Usage:
    python tests/manual/evaluation_smoke.py
"""

from pathlib import Path
import tempfile
import sys
import uuid

# Ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))

from job_automation.assessment.service import AssessmentService
from job_automation.contracts.assessment import Assessment, LLMAssessmentMetadata
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
)
from job_automation.contracts.interfaces import AssessorV2
from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.fingerprints import compute_canonical_fingerprint
from job_automation.evaluation.metrics import calculate_evaluation_metrics
from job_automation.evaluation.records import DependencyGateRegister, ExperimentManifest
from job_automation.evaluation.reporting import format_metric_report_text
from job_automation.evaluation.runner import EvaluationRunner
from job_automation.evaluation.settings import EvaluationSettings


class SmokeMockAssessor(AssessorV2):
    """Simple offline mock assessor for smoke verification."""

    def assess(self, request):
        from job_automation.assessment.llm_records import AssessmentRunResult

        disp = request.deterministic_baseline.final_disposition
        asmt = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=request.canonical_job_id,
            posting_revision=request.posting_revision,
            profile_version=request.profile.profile_version,
            policy_version=request.policy.policy_version,
            assessment_method=AssessmentMethod.LLM,
            final_disposition=disp,
            relevance_decision=disp,
            relevance_score=80.0,
            score_scale="0-100",
            summary_reason=f"Smoke mock eval output for {request.context_strategy.value}",
            model_metadata=LLMAssessmentMetadata(
                model_identifier="smoke-mock-model",
                prompt_version="v1",
                context_strategy=request.context_strategy,
            ),
            rule_outcomes=request.deterministic_baseline.rule_outcomes,
            requirement_findings=[],
        )
        return AssessmentRunResult(
            status="success",
            assessment=asmt,
            input_fingerprint="fp_smoke_test",
        )


def main() -> int:
    print("=" * 70)
    print("EVAL-01 MANUAL SMOKE TEST")
    print("=" * 70)

    with tempfile.TemporaryDirectory(prefix="Job_Eval_Smoke_") as temp_dir:
        eval_root = Path(temp_dir).resolve()
        print(f"Temporary evaluation root: {eval_root}")

        settings = EvaluationSettings(eval_root=str(eval_root))
        env = create_evaluation_environment(settings)

        try:
            # 1. Gates
            gates = DependencyGateRegister()
            print("\nDependency Gates:")
            for g in (
                gates.eg1_exact_frozen_inputs,
                gates.eg2_comparable_model_execution,
                gates.eg3_observable_evidence,
                gates.eg4_run_integration_and_isolation,
                gates.eg5_live_execution,
            ):
                print(f"  [{g.status:<18}] {g.gate_id}: {g.name}")

            # 2. Corpus
            corpus = EvaluationCorpus.default_synthetic()
            print(f"\nCorpus loaded: {len(corpus.cases)} canonical synthetic cases.")

            # 3. Experiment
            c0 = corpus.cases[0]
            manifest = ExperimentManifest(
                experiment_name="smoke_test_run",
                corpus_version="1.0",
                split_name="development",
                case_ids=[c.case_id for c in corpus.filter_split("development")],
                profile_snapshot_hash=compute_canonical_fingerprint(c0.profile),
                search_policy_fingerprint=compute_canonical_fingerprint(c0.policy),
                model_identifier="smoke-mock-model",
                model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                repetitions_per_pair=1,
            )

            # 4. Runner
            runner = EvaluationRunner(
                environment=env,
                assessment_service=AssessmentService(),
                llm_assessor=SmokeMockAssessor(),
            )
            print("\nExecuting paired runs...")
            results = runner.run_experiment(manifest, corpus)
            print(f"Completed {len(results)} pair(s).")

            # 5. Report
            report = calculate_evaluation_metrics(
                experiment_id=manifest.experiment_id,
                cases=corpus.filter_split("development"),
                pair_results=results,
            )
            print("\nMetric Report Output:")
            print(format_metric_report_text(report))

            # 6. Publication firewall
            assert not hasattr(runner.adapter, "salesforce_client")
            assert not hasattr(env.repository, "salesforce_client")
            assert settings.enable_sync is False
            print("\nFirewall check: PASSED (Zero Salesforce publication authority).")
            print("=" * 70)
            print("SMOKE TEST RESULT: SUCCESS")
            print("=" * 70)
            return 0
        finally:
            env.close()


if __name__ == "__main__":
    sys.exit(main())
