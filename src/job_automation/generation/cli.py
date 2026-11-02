"""Command-line interface commands for generation worker (GEN-01-S08)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.contracts.enums import GenerationProcessing
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.reporting import format_worker_report
from job_automation.generation.worker import GenerationWorker
from job_automation.storage.engine import StorageEngine


def register_generation_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'generation' subcommand group."""
    gen_parser = subparsers.add_parser("generation", help="Document generation worker and request lifecycle commands")
    gen_sub = gen_parser.add_subparsers(dest="generation_command", help="Generation actions")

    # generation work
    work_parser = gen_sub.add_parser("work", help="Run bounded generation worker polling and processing")
    work_parser.add_argument("--config", type=str, default=None, help="Path to JSON configuration file")
    work_parser.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    work_parser.add_argument("--once", action="store_true", default=True, help="Run a single bounded cycle (default)")
    work_parser.add_argument("--watch", action="store_true", default=False, help="Run continuously in foreground watch mode")
    work_parser.add_argument(
        "--through",
        type=str,
        default=None,
        choices=["freeze", "context", "draft", "validation", "rendering", "delivery"],
        help="Coordinate stages only through the specified stage (e.g. --through context)",
    )
    work_parser.add_argument("--json", action="store_true", default=False, help="Output report in JSON format")

    # generation show
    show_parser = gen_sub.add_parser("show", help="Inspect generation request state and stage checkpoints")
    show_parser.add_argument("--request-id", type=str, required=True, help="Generation request UUID to inspect")
    show_parser.add_argument("--config", type=str, default=None, help="Path to JSON configuration file")
    show_parser.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    show_parser.add_argument("--json", action="store_true", default=False, help="Output request in JSON format")

    # generation retry
    retry_parser = gen_sub.add_parser("retry", help="Retry a failed generation request with preserved identity")
    retry_parser.add_argument("--request-id", type=str, required=True, help="Generation request UUID to retry")
    retry_parser.add_argument("--config", type=str, default=None, help="Path to JSON configuration file")
    retry_parser.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    retry_parser.add_argument("--json", action="store_true", default=False, help="Output result in JSON format")


def handle_generation_commands(args: argparse.Namespace) -> int:
    """Dispatch generation CLI subcommands."""
    cmd = getattr(args, "generation_command", None)
    if cmd == "work":
        return _handle_work(args)
    elif cmd == "show":
        return _handle_show(args)
    elif cmd == "retry":
        return _handle_retry(args)
    else:
        print("Error: Must specify generation action: work, show, or retry", file=sys.stderr)
        return 2


def _handle_work(args: argparse.Namespace) -> int:
    try:
        worker = GenerationWorker(
            config_path=args.config,
            data_root=args.data_root,
        )
        if args.watch:
            worker.run_watch(stop_after_stage=args.through)
            return 0
        else:
            report = worker.run_once(stop_after_stage=args.through)
            output = format_worker_report(report, as_json=args.json)
            print(output)
            return report.exit_code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Generation worker failed: {exc}", file=sys.stderr)
        return 1


def _handle_show(args: argparse.Namespace) -> int:
    try:
        req_id = uuid.UUID(args.request_id)
    except ValueError:
        print(f"Error: Invalid UUID '{args.request_id}'", file=sys.stderr)
        return 2

    try:
        app_config, paths = load_config(config_path=args.config, data_root_override=args.data_root)
        engine = StorageEngine.from_config(app_config, paths)
        # Read-only inspection; no schema initialization or recovery
        req = engine.generation_requests.get_request(req_id)
        if req is None:
            print(f"Error: GenerationRequest '{req_id}' not found", file=sys.stderr)
            return 1

        checkpoints = engine.generation_work.list_checkpoints(req_id)
        deliveries = engine.generation_work.list_delivery_records(req_id)
        active_intent = engine.generation_work.get_active_projection_intent(req_id)

        if args.json:
            result = {
                "request": req.model_dump(),
                "checkpoints": [c.model_dump() for c in checkpoints],
                "deliveries": [d.model_dump() for d in deliveries],
                "active_projection_intent": active_intent.model_dump() if active_intent else None,
            }
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Generation Request Details")
            print("==========================")
            print(f"Request ID:           {req.request_id}")
            print(f"State:                {req.state.value}")
            print(f"Remote Record ID:     {req.salesforce_request_id or '(none)'}")
            print(f"Client Key:           {req.client_request_key or '(none)'}")
            print(f"Canonical Job ID:     {req.canonical_job_id}")
            print(f"Document Type:        {req.document_type.value}")
            print(f"Language:             {req.target_language}")
            print(f"Context Strategy:     {req.context_strategy.value}")
            print(f"Created:              {req.created_at.isoformat()}")
            print(f"Claimed:              {req.claimed_at.isoformat() if req.claimed_at else '(unclaimed)'}")
            print(f"Completed:            {req.completed_at.isoformat() if req.completed_at else '(pending)'}")
            if req.error:
                print(f"Error:                [{req.error.category.value}] {req.error.message}")

            if checkpoints:
                print("\nCheckpoints:")
                for c in checkpoints:
                    print(f"  - {c.stage_name:12}: {c.status.value:10} (started: {c.started_at.isoformat()})")

            if deliveries:
                print("\nDeliveries:")
                for d in deliveries:
                    print(f"  - {d.artifact_format.upper():4}: {d.delivery_status:12} remote_file_id={d.remote_file_id or 'none'}")

        return 0
    except Exception as exc:
        print(f"Show failed: {exc}", file=sys.stderr)
        return 1


def _handle_retry(args: argparse.Namespace) -> int:
    try:
        req_id = uuid.UUID(args.request_id)
    except ValueError:
        print(f"Error: Invalid UUID '{args.request_id}'", file=sys.stderr)
        return 2

    try:
        app_config, paths = load_config(config_path=args.config, data_root_override=args.data_root)
        engine = StorageEngine.from_config(app_config, paths)
        engine.initialize_schema()

        req = engine.generation_requests.get_request(req_id)
        if req is None:
            print(f"Error: GenerationRequest '{req_id}' not found", file=sys.stderr)
            return 1

        if req.state != GenerationProcessing.FAILED:
            print(f"Error: Request '{req_id}' is in state '{req.state.value}', not 'failed'. Only failed requests can be retried.", file=sys.stderr)
            return 2

        # Reset failed state to running or pending preserving frozen inputs
        reset_state = GenerationProcessing.RUNNING if req.frozen_input_versions else GenerationProcessing.PENDING
        retried_req = req.model_copy(
            update={
                "state": reset_state,
                "error": None,
                "completed_at": None,
            }
        )
        engine.generation_requests.update_request(retried_req)
        print(f"Request {req_id} reset to state '{reset_state.value}' for retry.")
        return 0
    except Exception as exc:
        print(f"Retry failed: {exc}", file=sys.stderr)
        return 1

