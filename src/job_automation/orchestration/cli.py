"""Command-line interface for pipeline orchestration (RUN-01-S08).

Commands:
  run start [--config <path>] [--data-root <path>] [--run-config <path>] [--assessment-mode {rules,llm}] [--json]
  run resume --run-id <uuid> [--config <path>] [--data-root <path>] [--json]
  run show --run-id <uuid> [--config <path>] [--data-root <path>] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from job_automation.orchestration.runner import PipelineRunner, RunOptions


def register_run_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register 'run' subcommand group into the root CLI parser."""
    run_parser = subparsers.add_parser(
        "run",
        help="Pipeline orchestration commands (start, resume, show)",
    )
    run_sub = run_parser.add_subparsers(dest="run_command", help="Run actions")

    # run start
    start_parser = run_sub.add_parser("start", help="Start a new discovery, assessment, and sync run")
    start_parser.add_argument("--config", type=str, default=None, help="Path to JSON configuration file")
    start_parser.add_argument("--data-root", type=str, default=None, help="Override runtime data root")
    start_parser.add_argument("--run-config", type=str, default=None, help="Path to run configuration JSON")
    start_parser.add_argument(
        "--assessment-mode",
        type=str,
        choices=["rules", "llm"],
        default=None,
        help="Assessment evaluation mode (default: rules)",
    )
    start_parser.add_argument(
        "--llm-strategy",
        "--strategy",
        dest="llm_strategy",
        type=str,
        choices=["json", "rag"],
        default=None,
        help="LLM strategy when assessment-mode is llm (default: json)",
    )
    start_parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="Optional subset of source keys to fetch (e.g. arbeitnow:berlin)",
    )
    start_parser.add_argument("--sync-config", type=str, default=None, help="Path to Salesforce sync mapping configuration JSON")
    start_parser.add_argument("--trigger-kind", type=str, default=None, help="Trigger kind (e.g. manual, scheduled, retry)")
    start_parser.add_argument("--schedule-occurrence-id", type=str, default=None, help="Schedule occurrence UUID if scheduled")
    start_parser.add_argument("--slot-key", type=str, default=None, help="Schedule slot key if scheduled")
    start_parser.add_argument("--no-sync", action="store_true", help="Disable Salesforce synchronization")
    start_parser.add_argument("--no-backup", action="store_true", help="Disable candidate field backup scan")
    start_parser.add_argument("--json", action="store_true", help="Output run report in structured JSON format")

    # run resume
    resume_parser = run_sub.add_parser("resume", help="Resume an interrupted or failed pipeline run")
    resume_parser.add_argument("--run-id", type=str, required=True, help="UUID of the run to resume")
    resume_parser.add_argument("--config", type=str, default=None, help="Path to JSON configuration file")
    resume_parser.add_argument("--data-root", type=str, default=None, help="Override runtime data root")
    resume_parser.add_argument("--json", action="store_true", help="Output run report in structured JSON format")

    # run show
    show_parser = run_sub.add_parser("show", help="Display summary and status of a previous run (read-only)")
    show_parser.add_argument("--run-id", type=str, required=True, help="UUID of the run to display")
    show_parser.add_argument("--config", type=str, default=None, help="Path to JSON configuration file")
    show_parser.add_argument("--data-root", type=str, default=None, help="Override runtime data root")
    show_parser.add_argument("--json", action="store_true", help="Output run summary in structured JSON format")


def handle_run_commands(args: argparse.Namespace) -> int:
    """Handle dispatched 'run' subcommands."""
    if not hasattr(args, "run_command") or args.run_command is None:
        print("Usage: job_automation run {start,resume,show} ...", file=sys.stderr)
        return 2

    # Parse run config overrides if provided
    run_cfg_path = getattr(args, "run_config", None)
    file_cfg: dict = {}
    if run_cfg_path is not None:
        p = Path(run_cfg_path)
        if not p.is_file():
            print(f"Error: Run configuration file not found: '{run_cfg_path}'", file=sys.stderr)
            return 2
        try:
            with open(p, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
        except Exception as exc:
            print(f"Error reading run config '{run_cfg_path}': {exc}", file=sys.stderr)
            return 2

    runner = PipelineRunner(
        config_path=args.config,
        data_root=args.data_root,
    )

    if args.run_command == "start":
        mode_cli = getattr(args, "assessment_mode", None)
        strategy_cli = getattr(args, "llm_strategy", None)
        mode = mode_cli or file_cfg.get("assessment_mode") or "rules"
        strategy = strategy_cli or file_cfg.get("llm_strategy") or file_cfg.get("strategy") or "json"
        sources = getattr(args, "sources", None) or file_cfg.get("sources", None)
        enable_sync = not getattr(args, "no_sync", False) and file_cfg.get("enable_sync", True)
        run_backup = not getattr(args, "no_backup", False) and file_cfg.get("run_candidate_backup", True)
        sync_cfg_path = getattr(args, "sync_config", None) or file_cfg.get("sync_config_path", None)

        opts = RunOptions(
            config_path=args.config,
            data_root=args.data_root,
            run_config_path=run_cfg_path,
            assessment_mode=mode,
            llm_strategy=strategy,
            sources=sources,
            enable_sync=enable_sync,
            run_candidate_backup=run_backup,
            sync_config_path=sync_cfg_path,
            json_output=getattr(args, "json", False),
            trigger_kind=getattr(args, "trigger_kind", None),
            schedule_occurrence_id=getattr(args, "schedule_occurrence_id", None),
            slot_key=getattr(args, "slot_key", None),
        )

        report = runner.start_run(options=opts)
        if getattr(args, "json", False):
            print(report.to_json())
        else:
            print(report.to_text())
        return report.exit_code

    if args.run_command == "resume":
        try:
            target_run_id = uuid.UUID(args.run_id)
        except ValueError:
            print(f"Invalid run ID '{args.run_id}': must be a valid UUID", file=sys.stderr)
            return 2

        opts = RunOptions(
            config_path=args.config,
            data_root=args.data_root,
            json_output=getattr(args, "json", False),
        )

        report = runner.resume_run(run_id=target_run_id, options=opts)
        if getattr(args, "json", False):
            print(report.to_json())
        else:
            print(report.to_text())
        return report.exit_code

    if args.run_command == "show":
        try:
            target_run_id = uuid.UUID(args.run_id)
        except ValueError:
            print(f"Invalid run ID '{args.run_id}': must be a valid UUID", file=sys.stderr)
            return 2

        report = runner.show_run(run_id=target_run_id)
        if report is None:
            print(f"Run '{target_run_id}' not found", file=sys.stderr)
            return 1

        if getattr(args, "json", False):
            print(report.to_json())
        else:
            print(report.to_text())
        return report.exit_code

    print(f"Unknown run action '{args.run_command}'", file=sys.stderr)
    return 2

