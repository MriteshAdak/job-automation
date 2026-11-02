"""Command-line interface for source registry inspection and selection checking (SOURCE-01-S07)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from job_automation.sources.service import SourceRegistryService


def register_sources_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register 'sources' subcommands under the main CLI argument parser."""
    sources_parser = subparsers.add_parser(
        "sources",
        help="Source registry inspection, validation, and preflight selection checking",
    )
    sources_sub = sources_parser.add_subparsers(dest="sources_command", help="Sources actions")

    # check subcommand
    check_parser = sources_sub.add_parser(
        "check",
        help="Validate source configuration, access review, and selection readiness",
    )
    check_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to application config JSON resolving source_registry_ref",
    )
    check_parser.add_argument(
        "--registry",
        type=str,
        default=None,
        help="Direct path to source registry JSON file",
    )
    check_parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        default=None,
        help="Specific source key to select and check (repeatable)",
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

    # list subcommand
    list_parser = sources_sub.add_parser(
        "list",
        help="List all configured sources with readiness status and inventory scope",
    )
    list_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to application config JSON resolving source_registry_ref",
    )
    list_parser.add_argument(
        "--registry",
        type=str,
        default=None,
        help="Direct path to source registry JSON file",
    )
    list_parser.add_argument(
        "--data-root",
        type=str,
        default=None,
        help="Override path for runtime data root (used with --config)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output machine-readable JSON result",
    )


def handle_sources_commands(args: argparse.Namespace) -> int:
    """Dispatch sources subcommands."""
    if args.sources_command == "check":
        return run_sources_check(
            config_path=args.config,
            registry_path=args.registry,
            explicit_sources=args.sources,
            data_root=args.data_root,
            as_json=args.json,
        )
    if args.sources_command == "list":
        return run_sources_list(
            config_path=args.config,
            registry_path=args.registry,
            data_root=args.data_root,
            as_json=args.json,
        )

    print("Unrecognized sources action. Use --help for available actions.", file=sys.stderr)
    return 2


def run_sources_check(
    config_path: str | None,
    registry_path: str | None,
    explicit_sources: list[str] | None,
    data_root: str | None,
    as_json: bool,
) -> int:
    """Execute sources check command and return exit code 0 on valid selection, 2 on blocker/error."""
    try:
        requested_keys: list[str]
        if registry_path is not None and config_path is None:
            service = SourceRegistryService.load_from_path(registry_path)
            requested_keys = explicit_sources if explicit_sources is not None else []
        else:
            service, _, active_sources = SourceRegistryService.load_from_config(
                config_path=config_path,
                data_root_override=data_root,
                registry_override=registry_path,
            )
            requested_keys = explicit_sources if explicit_sources is not None else active_sources

        res = service.select_sources(requested_keys)

        if as_json:
            payload: dict[str, Any] = {
                "is_valid": res.is_valid,
                "requested_keys": res.requested_keys,
                "selected_count": len(res.selected_sources),
                "blockers": res.blockers,
                "selected_sources": [
                    {
                        "source_key": s.config.source_key,
                        "provider": s.config.provider,
                        "board_id": s.config.board_id,
                        "acquisition_method": s.config.acquisition_method.value,
                        "inventory_semantics": s.config.inventory_semantics.value,
                        "scope_id": s.inventory_scope.scope_id,
                        "enabled": s.config.enabled,
                        "access_status": s.access_review.status.value,
                        "attribution_status": s.attribution_review.status.value,
                    }
                    for s in res.selected_sources
                ],
                "all_sources_count": len(res.all_sources),
            }
            print(json.dumps(payload, indent=2))
        else:
            if res.is_valid:
                print("Sources check: VALID")
                print(f"  Requested Sources: {res.requested_keys}")
                print(f"  Selected Count:    {len(res.selected_sources)}")
                for s in res.selected_sources:
                    print(f"    - {s.config.source_key} [{s.config.provider}/{s.config.board_id}]")
                    print(f"        Method:    {s.config.acquisition_method.value}")
                    print(f"        Semantics: {s.config.inventory_semantics.value}")
                    print(f"        Scope ID:  {s.inventory_scope.scope_id}")
            else:
                print("Sources check: FAILED", file=sys.stderr)
                print(f"  Requested Sources: {res.requested_keys}", file=sys.stderr)
                print(f"  Blockers ({len(res.blockers)}):", file=sys.stderr)
                for b in res.blockers:
                    print(f"    - {b}", file=sys.stderr)

        return 0 if res.is_valid else 2

    except Exception as exc:
        safe_msg = str(exc)
        if as_json:
            print(json.dumps({"is_valid": False, "error": safe_msg, "blockers": [safe_msg]}))
        else:
            print(f"Sources check: FAILED\n  Error: {safe_msg}", file=sys.stderr)
        return 2


def run_sources_list(
    config_path: str | None,
    registry_path: str | None,
    data_root: str | None,
    as_json: bool,
) -> int:
    """Execute sources list command displaying all configured sources in the registry."""
    try:
        if registry_path is not None and config_path is None:
            service = SourceRegistryService.load_from_path(registry_path)
        else:
            service, _, _ = SourceRegistryService.load_from_config(
                config_path=config_path,
                data_root_override=data_root,
                registry_override=registry_path,
            )

        sources = service.list_sources()

        if as_json:
            payload = {
                "source_count": len(sources),
                "sources": [
                    {
                        "source_key": s.config.source_key,
                        "provider": s.config.provider,
                        "board_id": s.config.board_id,
                        "acquisition_method": s.config.acquisition_method.value,
                        "inventory_semantics": s.config.inventory_semantics.value,
                        "scope_id": s.inventory_scope.scope_id,
                        "enabled": s.config.enabled,
                        "is_valid": s.is_valid,
                        "is_runnable": s.is_runnable,
                        "access_status": s.access_review.status.value,
                        "attribution_status": s.attribution_review.status.value,
                        "readiness_blockers": s.readiness_blockers,
                    }
                    for s in sources
                ],
            }
            print(json.dumps(payload, indent=2))
        else:
            print(f"Configured Sources ({len(sources)}):")
            for s in sources:
                runnable_tag = "READY" if s.is_runnable else "BLOCKED"
                enabled_tag = "ENABLED" if s.config.enabled else "DISABLED"
                print(
                    f"  [{runnable_tag}] [{enabled_tag}] {s.config.source_key} "
                    f"({s.config.provider}/{s.config.board_id})"
                )
                print(f"      Method:      {s.config.acquisition_method.value}")
                print(f"      Semantics:   {s.config.inventory_semantics.value}")
                print(f"      Scope ID:    {s.inventory_scope.scope_id}")
                print(f"      Access:      {s.access_review.status.value}")
                print(f"      Attribution: {s.attribution_review.status.value}")
                if s.readiness_blockers:
                    print("      Readiness Blockers:")
                    for b in s.readiness_blockers:
                        print(f"        - {b}")

        return 0

    except Exception as exc:
        safe_msg = str(exc)
        if as_json:
            print(json.dumps({"error": safe_msg, "sources": []}))
        else:
            print(f"Sources list: FAILED\n  Error: {safe_msg}", file=sys.stderr)
        return 2

