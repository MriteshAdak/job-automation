"""Command-line interface for search policy validation and checking."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from job_automation.policy.service import PolicyService


def register_policy_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register 'policy' subcommands under the main CLI argument parser."""
    policy_parser = subparsers.add_parser(
        "policy",
        help="Search policy and vocabulary inspection and validation",
    )
    policy_sub = policy_parser.add_subparsers(dest="policy_command", help="Policy actions")

    check_parser = policy_sub.add_parser(
        "check",
        help="Validate search policy semantics, aliases, and compute fingerprint",
    )
    check_parser.add_argument(
        "--policy",
        type=str,
        default=None,
        help="Direct path to search policy JSON file",
    )
    check_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to application config JSON resolving active_policy_ref",
    )
    check_parser.add_argument(
        "--data-root",
        type=str,
        default=None,
        help="Override path for runtime data root (used with --config)",
    )
    check_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output machine-readable JSON result",
    )


def handle_policy_commands(args: argparse.Namespace) -> int:
    """Dispatch policy subcommands."""
    if args.policy_command == "check":
        return run_policy_check(
            policy_path=args.policy,
            config_path=args.config,
            data_root=args.data_root,
            as_json=args.json,
        )

    print("Unrecognized policy action. Use --help for available actions.", file=sys.stderr)
    return 2


def run_policy_check(
    policy_path: str | None,
    config_path: str | None,
    data_root: str | None,
    as_json: bool,
) -> int:
    """Execute search policy check command."""
    # Enforce exactly one source: either --policy or --config
    if policy_path is None and config_path is None:
        msg = "Must specify either --policy <path> or --config <path>"
        if as_json:
            print(json.dumps({"is_valid": False, "error": msg, "fingerprint": None}))
        else:
            print(f"Policy check: FAILED\n  Error: {msg}", file=sys.stderr)
        return 2

    if policy_path is not None and config_path is not None:
        msg = "Cannot specify both --policy and --config; specify exactly one source"
        if as_json:
            print(json.dumps({"is_valid": False, "error": msg, "fingerprint": None}))
        else:
            print(f"Policy check: FAILED\n  Error: {msg}", file=sys.stderr)
        return 2

    if policy_path is not None:
        res = PolicyService.load_and_validate(policy_path)
    else:
        res = PolicyService.load_from_config(config_path, data_root_override=data_root)

    if as_json:
        payload: dict[str, Any] = {
            "is_valid": res.is_valid,
            "fingerprint": res.fingerprint,
            "effective_version": res.fingerprint,
            "authored_version": (
                res.effective_policy.metadata.authored_version
                if res.effective_policy
                else None
            ),
            "schema_version": (
                res.effective_policy.metadata.schema_version
                if res.effective_policy
                else "1.0"
            ),
            "issues": [i.model_dump() for i in res.issues],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if res.is_valid else 2

    # Human-readable output
    if not res.is_valid:
        print("Policy check: FAILED", file=sys.stderr)
        for issue in res.errors:
            print(f"  [ERROR] {issue.field_path}: ({issue.code}) {issue.message}", file=sys.stderr)
        for issue in res.warnings:
            print(f"  [WARN]  {issue.field_path}: ({issue.code}) {issue.message}", file=sys.stderr)
        return 2

    meta = res.effective_policy.metadata
    pol = res.effective_policy.policy
    print("Policy check: VALID")
    print(f"  Authored Version:  {meta.authored_version}")
    print(f"  Effective Version: {meta.effective_version}")
    print(f"  Fingerprint:       {res.fingerprint}")
    print(f"  Context Strategy:  {pol.primary_context_strategy.value}")
    print(f"  Regions:           {pol.regions}")
    print(f"  Hard Criteria:     {len(pol.hard_criteria)}")
    print(f"  Preferences:       {len(pol.preferences)}")
    print(f"  Exclusions:        {len(pol.exclusions)}")

    if res.warnings:
        print(f"  Warnings ({len(res.warnings)}):")
        for issue in res.warnings:
            print(f"    [WARN] {issue.field_path}: ({issue.code}) {issue.message}")

    return 0

