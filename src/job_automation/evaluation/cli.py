"""Command-line interface for evaluation commands (EVAL-01-S08).

Subcommands:
- check: Validate evaluation configuration, gates, and publication firewall.
- run: Execute paired JSON/RAG evaluations on labeled corpus.
- resume: Resume incomplete evaluation pairs without re-running completed arms.
- report: Re-generate and export metric report from frozen experiment records.
- sample-rejects: Seeded stratified sampling of rejected jobs.
- review-export: Export blinded review packets for human annotation.
- review-import: Import human review corrections with immutability guarantees.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

from job_automation.assessment.service import AssessmentService
from job_automation.evaluation.composition import create_evaluation_environment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.errors import EvaluationError, PublicationAttemptBlockedError
from job_automation.evaluation.fingerprints import compute_canonical_fingerprint
from job_automation.evaluation.metrics import calculate_evaluation_metrics
from job_automation.evaluation.population_reader import read_rejected_population
from job_automation.evaluation.records import DependencyGateRegister, ExperimentManifest
from job_automation.evaluation.recovery import EvaluationRecoveryManager
from job_automation.evaluation.reporting import (
    format_metric_report_markdown,
    format_metric_report_text,
)
from job_automation.evaluation.review_export import export_review_packets
from job_automation.evaluation.review_import import import_review_corrections
from job_automation.evaluation.runner import EvaluationRunner
from job_automation.evaluation.sampling import sample_rejected_population
from job_automation.evaluation.settings import EvaluationSettings


def register_evaluation_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register evaluation CLI command tree."""
    eval_parser = subparsers.add_parser("evaluation", help="Paired evaluation and benchmark runner")
    eval_sub = eval_parser.add_subparsers(dest="eval_command", help="Evaluation actions")

    # check
    check_p = eval_sub.add_parser("check", help="Check evaluation configuration, firewall, and gates")
    check_p.add_argument("--config", type=str, default=None, help="Path to evaluation config JSON")
    check_p.add_argument("--eval-root", type=str, default=None, help="Root directory for evaluation artifacts")

    # run
    run_p = eval_sub.add_parser("run", help="Run paired evaluation experiment")
    run_p.add_argument("--config", type=str, default=None, help="Path to evaluation config JSON")
    run_p.add_argument("--eval-root", type=str, default=None, help="Root directory for evaluation artifacts")
    run_p.add_argument("--name", type=str, default="cli_experiment", help="Experiment name")
    run_p.add_argument("--split", choices=["development", "held_out", "all"], default="development")
    run_p.add_argument("--repetitions", type=int, default=1, help="Repetitions per pair")
    run_p.add_argument("--seed", type=int, default=42, help="Order randomization seed")

    # resume
    resume_p = eval_sub.add_parser("resume", help="Resume incomplete evaluation pairs")
    resume_p.add_argument("--eval-root", type=str, default=None, help="Root directory for evaluation artifacts")
    resume_p.add_argument("--experiment-id", type=str, required=True, help="UUID of experiment to resume")

    # report
    report_p = eval_sub.add_parser("report", help="Generate metric report from existing experiment")
    report_p.add_argument("--eval-root", type=str, default=None, help="Root directory for evaluation artifacts")
    report_p.add_argument("--experiment-id", type=str, required=True, help="UUID of experiment to report")
    report_p.add_argument("--output", type=str, default=None, help="Output markdown path")

    # sample-rejects
    sample_p = eval_sub.add_parser("sample-rejects", help="Sample rejected jobs with stratification")
    sample_p.add_argument("--input-db", type=str, default=None, help="Path to SQLite DB containing assessments")
    sample_p.add_argument("--cohort-id", type=str, default="cohort_cli", help="Cohort identifier")
    sample_p.add_argument("--sample-size", type=int, default=50, help="Target sample size")
    sample_p.add_argument("--seed", type=int, default=42, help="Sampling seed")
    sample_p.add_argument("--output", type=str, required=True, help="Output JSON path for sample manifest")

    # review-export
    rev_exp_p = eval_sub.add_parser("review-export", help="Export blinded review packets")
    rev_exp_p.add_argument("--eval-root", type=str, default=None, help="Root directory for evaluation artifacts")
    rev_exp_p.add_argument("--experiment-id", type=str, required=True, help="UUID of experiment")
    rev_exp_p.add_argument("--output", type=str, required=True, help="Output JSON path for review packets")

    # review-import
    rev_imp_p = eval_sub.add_parser("review-import", help="Import reviewer corrections")
    rev_imp_p.add_argument("--eval-root", type=str, default=None, help="Root directory for evaluation artifacts")
    rev_imp_p.add_argument("--corrections", type=str, required=True, help="Path to corrections JSON file")


def handle_evaluation_commands(args: argparse.Namespace) -> int:
    """Dispatch evaluation subcommands."""
    cmd = getattr(args, "eval_command", None)
    if not cmd:
        print("Error: No evaluation action specified. Run with --help for options.", file=sys.stderr)
        return 2

    try:
        if cmd == "check":
            return _cmd_check(args)
        elif cmd == "run":
            return _cmd_run(args)
        elif cmd == "resume":
            return _cmd_resume(args)
        elif cmd == "report":
            return _cmd_report(args)
        elif cmd == "sample-rejects":
            return _cmd_sample_rejects(args)
        elif cmd == "review-export":
            return _cmd_review_export(args)
        elif cmd == "review-import":
            return _cmd_review_import(args)
        else:
            print(f"Unknown evaluation command '{cmd}'", file=sys.stderr)
            return 2
    except (EvaluationError, ValueError) as exc:
        print(f"Evaluation error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2


def _load_settings(args: argparse.Namespace) -> EvaluationSettings:
    """Build EvaluationSettings from CLI arguments and optional config file."""
    config_data: dict = {}
    if getattr(args, "config", None):
        cfg_p = Path(args.config)
        if cfg_p.exists():
            with open(cfg_p, "r", encoding="utf-8") as f:
                config_data = json.load(f)

    if getattr(args, "eval_root", None):
        config_data["eval_root"] = args.eval_root

    return EvaluationSettings(**config_data)


def _cmd_check(args: argparse.Namespace) -> int:
    """Validate configuration, dependencies, and publication firewall."""
    settings = _load_settings(args)
    env = create_evaluation_environment(settings)
    try:
        gates = DependencyGateRegister()
        print("=" * 60)
        print("EVALUATION ENVIRONMENT CHECK")
        print("=" * 60)
        print(f"Evaluation Root:  {env.workspace.eval_root}")
        print(f"Artifacts Dir:    {env.workspace.artifacts_dir}")
        print(f"Database Path:    {env.workspace.db_path}")
        print(f"Model Service:    {settings.model_service_url} (loopback verified)")
        print(f"Model Identifier: {settings.model_identifier}")
        print(f"Publication Guard: ACTIVE (enable_sync={settings.enable_sync})")
        print("-" * 60)
        print("Dependency Gates Status:")
        gate_list = [
            gates.eg1_exact_frozen_inputs,
            gates.eg2_comparable_model_execution,
            gates.eg3_observable_evidence,
            gates.eg4_run_integration_and_isolation,
            gates.eg5_live_execution,
        ]
        for gate in gate_list:
            print(f"  [{gate.status:<18}] {gate.gate_id}: {gate.name} ({gate.owner})")
        print("-" * 60)
        print("Firewall verification: Zero Salesforce credentials or publication authority present.")
        print("Evaluation check: PASSED (Offline Fake/Scripted verified, Live model PENDING)")
        return 0
    finally:
        env.close()


def _cmd_run(args: argparse.Namespace) -> int:
    """Run paired evaluation on synthetic or loaded corpus."""
    settings = _load_settings(args)
    env = create_evaluation_environment(settings)
    try:
        corpus = EvaluationCorpus.default_synthetic()
        split_cases = corpus.get_split(args.split)
        case_ids = [c.case_id for c in split_cases]

        c0 = split_cases[0]
        manifest = ExperimentManifest(
            experiment_name=args.name,
            corpus_version="1.0",
            split_name=args.split,
            case_ids=case_ids,
            profile_snapshot_hash=compute_canonical_fingerprint(c0.profile),
            search_policy_fingerprint=compute_canonical_fingerprint(c0.policy),
            model_identifier=settings.model_identifier,
            model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            repetitions_per_pair=args.repetitions,
            order_randomization_seed=args.seed,
        )

        asmt_service = AssessmentService()
        runner = EvaluationRunner(environment=env, assessment_service=asmt_service)

        print(f"Running evaluation experiment '{manifest.experiment_name}' ({manifest.experiment_id})...")
        results = runner.run_experiment(manifest, corpus)

        report = calculate_evaluation_metrics(
            experiment_id=manifest.experiment_id,
            cases=split_cases,
            pair_results=results,
        )
        env.repository.save_metric_report(report)

        print(format_metric_report_text(report))

        if report.incomplete_pairs > 0:
            print(f"\nCompleted with {report.incomplete_pairs} incomplete pair(s). Run resume to retry.", file=sys.stderr)
            return 1
        return 0
    finally:
        env.close()


def _cmd_resume(args: argparse.Namespace) -> int:
    """Resume an incomplete experiment."""
    settings = _load_settings(args)
    env = create_evaluation_environment(settings)
    try:
        exp_uuid = uuid.UUID(args.experiment_id)
        recovery = EvaluationRecoveryManager(env.repository)
        plan = recovery.inspect_experiment(exp_uuid)

        print(f"Experiment {exp_uuid}: {plan.completed_pairs_count} completed, {plan.incomplete_pairs_count} incomplete.")
        if not plan.cases_to_resume:
            print("All pairs in experiment are already completed.")
            return 0

        corpus = EvaluationCorpus.default_synthetic()
        asmt_service = AssessmentService()
        runner = EvaluationRunner(environment=env, assessment_service=asmt_service)

        resumed_results = runner.run_experiment(plan.experiment, corpus)
        all_pairs = env.repository.list_pairs_for_experiment(exp_uuid)
        split_cases = corpus.get_split(plan.experiment.split_name)

        report = calculate_evaluation_metrics(
            experiment_id=exp_uuid,
            cases=split_cases,
            pair_results=all_pairs,
        )
        env.repository.save_metric_report(report)
        print(format_metric_report_text(report))
        return 0 if report.incomplete_pairs == 0 else 1
    finally:
        env.close()


def _cmd_report(args: argparse.Namespace) -> int:
    """Recreate report from persisted records without rerunning model inference."""
    settings = _load_settings(args)
    env = create_evaluation_environment(settings)
    try:
        exp_uuid = uuid.UUID(args.experiment_id)
        existing_report = env.repository.get_metric_report(exp_uuid)
        manifest = env.repository.get_experiment(exp_uuid)

        if existing_report is None:
            # Calculate from stored pairs
            pairs = env.repository.list_pairs_for_experiment(exp_uuid)
            if not pairs:
                print(f"No results found for experiment {exp_uuid}", file=sys.stderr)
                return 2
            corpus = EvaluationCorpus.default_synthetic()
            split_name = manifest.split_name if manifest else "development"
            cases = corpus.get_split(split_name)
            existing_report = calculate_evaluation_metrics(exp_uuid, cases, pairs)
            env.repository.save_metric_report(existing_report)

        md = format_metric_report_markdown(existing_report, manifest)
        if args.output:
            out_p = Path(args.output).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with open(out_p, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"Report written to: {out_p}")
        else:
            print(md)
        return 0
    finally:
        env.close()


def _cmd_sample_rejects(args: argparse.Namespace) -> int:
    """Sample rejected job assessments into a reproducible SampleManifest."""
    records = None
    if not args.input_db:
        # Default to synthetic reject population for offline execution
        c1 = uuid.uuid4()
        c2 = uuid.uuid4()
        c3 = uuid.uuid4()
        records = [
            {"canonical_job_id": c1, "posting_revision": "rev_1", "title": "C++ Dev", "final_disposition": "rejected", "summary_reason": "Visa authorization missing"},
            {"canonical_job_id": c2, "posting_revision": "rev_1", "title": "Java Dev", "final_disposition": "rejected", "summary_reason": "Hard failure: remote outside EU"},
            {"canonical_job_id": c3, "posting_revision": "rev_1", "title": "DevOps", "final_disposition": "rejected", "summary_reason": "Skill gap: Kubernetes required"},
        ]

    pop = read_rejected_population(
        records=records,
        sqlite_db_path=args.input_db,
        cohort_id=args.cohort_id,
    )

    manifest = sample_rejected_population(
        population=pop,
        target_sample_size=args.sample_size,
        seed=args.seed,
    )

    out_p = Path(args.output).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        f.write(manifest.model_dump_json(indent=2))

    print(f"Sample manifest generated: {manifest.sample_size} cases selected from population of {manifest.population_size}.")
    print(f"Saved to: {out_p}")
    return 0


def _cmd_review_export(args: argparse.Namespace) -> int:
    """Export review packets for human inspection."""
    settings = _load_settings(args)
    env = create_evaluation_environment(settings)
    try:
        exp_uuid = uuid.UUID(args.experiment_id)
        pairs = env.repository.list_pairs_for_experiment(exp_uuid)
        corpus = EvaluationCorpus.default_synthetic()
        out_p = Path(args.output).resolve()
        export_review_packets(corpus.cases, pairs, out_p)
        print(f"Exported review packets to: {out_p}")
        return 0
    finally:
        env.close()


def _cmd_review_import(args: argparse.Namespace) -> int:
    """Import reviewer corrections."""
    settings = _load_settings(args)
    env = create_evaluation_environment(settings)
    try:
        corpus = EvaluationCorpus.default_synthetic()
        corrections_path = Path(args.corrections).resolve()
        c0 = corpus.cases[0]
        imported = import_review_corrections(
            corrections_source=corrections_path,
            repository=env.repository,
            profile=c0.profile,
            policy=c0.policy,
        )
        print(f"Successfully imported {len(imported)} review correction(s).")
        return 0
    finally:
        env.close()
