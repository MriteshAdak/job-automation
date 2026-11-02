"""Command-line interface commands for automatic drafting (AUTO-02-S06)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.automatic.records import AutomaticDraftPolicy
from job_automation.generation.automatic.reporting import format_evaluation_report
from job_automation.generation.automatic.service import AutomaticDraftService
from job_automation.generation.automatic.settings import load_automatic_draft_policy
from job_automation.storage.engine import StorageEngine


def register_auto_draft_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'auto-draft' subcommand group."""
    auto_parser = subparsers.add_parser("auto-draft", help="Automatic drafting policy evaluation and inspection")
    auto_sub = auto_parser.add_subparsers(dest="auto_draft_command", help="Auto-draft actions")

    # auto-draft evaluate
    eval_parser = auto_sub.add_parser("evaluate", help="Evaluate automatic drafting policy against eligible candidates")
    eval_parser.add_argument("--config", type=str, default=None, help="Path to JSON application config")
    eval_parser.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    eval_parser.add_argument("--policy", type=str, default=None, help="Path to automatic draft policy JSON")
    eval_parser.add_argument("--preview", action="store_true", default=False, help="Run in preview mode (zero writes or request creations)")
    eval_parser.add_argument("--dry-run", dest="preview", action="store_true", help="Alias for --preview")
    eval_parser.add_argument("--json", action="store_true", default=False, help="Output report in JSON format")

    # auto-draft show
    show_parser = auto_sub.add_parser("show", help="Inspect decisions and intents for a canonical job or key")
    show_parser.add_argument("--job-id", type=str, default=None, help="Canonical job UUID to inspect")
    show_parser.add_argument("--intent-key", type=str, default=None, help="Client request key to inspect")
    show_parser.add_argument("--decision-id", type=str, default=None, help="Decision UUID to inspect")
    show_parser.add_argument("--config", type=str, default=None, help="Path to JSON application config")
    show_parser.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    show_parser.add_argument("--json", action="store_true", default=False, help="Output in JSON format")


def run_auto_draft_cli(args: argparse.Namespace) -> int:
    """Entry point for auto-draft subcommands."""
    subcmd = getattr(args, "auto_draft_command", None)
    if subcmd == "evaluate":
        return _run_evaluate(args)
    elif subcmd == "show":
        return _run_show(args)
    else:
        print("Usage: python -m job_automation auto-draft [evaluate|show] --help", file=sys.stderr)
        return 2


def _run_evaluate(args: argparse.Namespace) -> int:
    try:
        config, paths = load_config(
            config_path=args.config,
            data_root_override=args.data_root,
        )
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    # Resolve policy path: CLI flag > paths.automatic_draft_policy_path > disabled default
    policy_path = args.policy
    if not policy_path and hasattr(paths, "automatic_draft_policy_path") and paths.automatic_draft_policy_path:
        policy_path = str(paths.automatic_draft_policy_path)

    if not policy_path:
        # Construct disabled default policy
        policy = AutomaticDraftPolicy(
            policy_id="default-disabled",
            policy_version="v1.0",
            enabled=False,
            candidate_id=uuid.uuid4(),
            salesforce_org_id="00D000000000001EAA",
        )
    else:
        policy, err = load_automatic_draft_policy(policy_path)
        if err is not None or policy is None:
            print(f"Policy load error: {err.message if err else 'unknown'}", file=sys.stderr)
            return 2

    with StorageEngine.from_config(config, paths) as engine:
        engine.initialize_schema()
        service = AutomaticDraftService(engine=engine)
        report = service.evaluate_and_process(policy=policy, preview=args.preview)

        output = format_evaluation_report(report, as_json=args.json)
        print(output)

    return 0


def _run_show(args: argparse.Namespace) -> int:
    try:
        config, paths = load_config(
            config_path=args.config,
            data_root_override=args.data_root,
        )
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    with StorageEngine.from_config(config, paths) as engine:
        engine.initialize_schema()

        if args.job_id:
            try:
                job_uuid = uuid.UUID(args.job_id)
            except ValueError:
                print(f"Invalid UUID: {args.job_id}", file=sys.stderr)
                return 2
            decisions = engine.automatic_drafts.list_decisions_for_job(job_uuid)
            intents = engine.automatic_drafts.list_intents_for_job(job_uuid)
            if args.json:
                print(json.dumps({
                    "job_id": str(job_uuid),
                    "decisions": [d.model_dump(mode="json") for d in decisions],
                    "intents": [i.model_dump(mode="json") for i in intents],
                }, indent=2))
            else:
                print(f"Job {job_uuid}: {len(decisions)} decisions, {len(intents)} intents")
                for d in decisions:
                    print(f"  Decision {d.decision_id} [{d.outcome.value}]: {d.summary_reason}")
                for i in intents:
                    print(f"  Intent {i.client_request_key} [{i.submission_state.value}]: {i.document_type.value}")
            return 0

        if args.intent_key:
            intent = engine.automatic_drafts.get_intent_by_key(args.intent_key)
            if intent is None:
                print(f"Intent not found for key: {args.intent_key}", file=sys.stderr)
                return 1
            if args.json:
                print(intent.model_dump_json(indent=2))
            else:
                print(f"Intent {intent.client_request_key}:")
                print(f"  State:         {intent.submission_state.value}")
                print(f"  Document Type: {intent.document_type.value}")
                print(f"  Job UUID:      {intent.canonical_job_id}")
                print(f"  Local Req ID:  {intent.local_request_id}")
            return 0

        if args.decision_id:
            try:
                dec_uuid = uuid.UUID(args.decision_id)
            except ValueError:
                print(f"Invalid UUID: {args.decision_id}", file=sys.stderr)
                return 2
            dec = engine.automatic_drafts.get_decision(dec_uuid)
            if dec is None:
                print(f"Decision not found: {dec_uuid}", file=sys.stderr)
                return 1
            if args.json:
                print(dec.model_dump_json(indent=2))
            else:
                print(f"Decision {dec.decision_id}:")
                print(f"  Outcome: {dec.outcome.value}")
                print(f"  Reasons: {', '.join(dec.reason_codes)}")
                print(f"  Summary: {dec.summary_reason}")
            return 0

    print("Please specify --job-id, --intent-key, or --decision-id to inspect.", file=sys.stderr)
    return 2

