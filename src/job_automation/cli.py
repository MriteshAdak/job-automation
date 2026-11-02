"""Command-line interface for foundation configuration checking.

Provides clean native Windows execution:
  python -m job_automation --help
  python -m job_automation --version
  python -m job_automation config check --config <path> --data-root <path>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from job_automation import __version__
from job_automation.configuration import load_config


def create_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="job_automation",
        description="Job search automation — foundation configuration and diagnostic runner",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # config subcommand group
    config_parser = subparsers.add_parser("config", help="Configuration inspection and validation")
    config_sub = config_parser.add_subparsers(dest="config_command", help="Config actions")

    check_parser = config_sub.add_parser("check", help="Validate configuration and resolve paths")
    check_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON configuration file",
    )
    check_parser.add_argument(
        "--data-root",
        type=str,
        default=None,
        help="Override path for runtime data root",
    )

    # storage subcommand group
    storage_parser = subparsers.add_parser("storage", help="Database storage and migration commands")
    storage_sub = storage_parser.add_subparsers(dest="storage_command", help="Storage actions")

    migrate_parser = storage_sub.add_parser("migrate", help="Run database migrations")
    migrate_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON configuration file",
    )
    migrate_parser.add_argument(
        "--data-root",
        type=str,
        default=None,
        help="Override path for runtime data root",
    )
    migrate_parser.add_argument(
        "--target-version",
        type=int,
        default=None,
        help="Target schema migration version (optional)",
    )

    status_parser = storage_sub.add_parser("status", help="Show database migration and schema status")
    status_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to JSON configuration file",
    )
    status_parser.add_argument(
        "--data-root",
        type=str,
        default=None,
        help="Override path for runtime data root",
    )

    # profile subcommand group
    from job_automation.profile.cli import register_profile_subparsers

    register_profile_subparsers(subparsers)

    # policy subcommand group
    from job_automation.policy.cli import register_policy_subparsers

    register_policy_subparsers(subparsers)

    # sources subcommand group
    from job_automation.sources.cli import register_sources_subparsers

    register_sources_subparsers(subparsers)

    # identity subcommand group
    from job_automation.identity.cli import register_identity_subparsers

    register_identity_subparsers(subparsers)

    # context subcommand group
    from job_automation.context.index_cli import register_context_subparsers

    register_context_subparsers(subparsers)

    # run subcommand group (RUN-01)
    from job_automation.orchestration.cli import register_run_subparsers

    register_run_subparsers(subparsers)

    # evaluation subcommand group (EVAL-01)
    from job_automation.evaluation.cli import register_evaluation_subparsers

    register_evaluation_subparsers(subparsers)

    # ops subcommand group (OPS-01)
    from job_automation.operations.cli import register_ops_subparsers

    register_ops_subparsers(subparsers)

    # generation subcommand group (GEN-01)
    from job_automation.generation.cli import register_generation_subparsers

    register_generation_subparsers(subparsers)

    # auto-draft subcommand group (AUTO-02)
    from job_automation.generation.automatic.cli import register_auto_draft_subparsers

    register_auto_draft_subparsers(subparsers)

    # delivery subcommand group (AUTO-03)
    from job_automation.orchestration.summary_delivery.cli import register_delivery_subparsers

    register_delivery_subparsers(subparsers)

    return parser


def run_config_check(config_path: str | None, data_root: str | None) -> int:
    """Execute config check command and output safe allowlisted summary."""
    try:
        config, paths = load_config(
            config_path=config_path,
            data_root_override=data_root,
        )

        print("Configuration check: VALID")
        print(f"  App Name:          {config.app_name}")
        print(f"  Schema Version:    {config.schema_version}")
        print(f"  Timezone:          {config.display_timezone}")
        print(f"  Model Service:     {config.model_service_url}")
        print(f"  Data Root:         {paths.data_root}")
        print(f"  Profiles Path:     {paths.profiles_dir}")
        print(f"  Raw Snapshots:     {paths.raw_dir}")
        print(f"  Database Path:     {paths.database_path}")
        print(f"  Artifacts Path:    {paths.artifacts_dir}")
        print(f"  Logs Path:         {paths.logs_dir}")
        print(f"  Backups Path:      {paths.backups_dir}")
        if paths.policy_path:
            print(f"  Policy Reference:  {paths.policy_path}")
        if paths.source_registry_path:
            print(f"  Source Registry:   {paths.source_registry_path}")
        return 0

    except Exception as exc:
        # Safe error output without echoing secret payload or credentials
        err_msg = str(exc)
        import re
        safe_msg = re.sub(r"://[^@]+@", "://[REDACTED]@", err_msg)
        safe_msg = safe_msg.replace("SECRET_SENTINEL", "[REDACTED]")
        print(f"Configuration check: FAILED\n  Error: {safe_msg}", file=sys.stderr)
        return 2


def run_storage_migrate(
    config_path: str | None,
    data_root: str | None,
    target_version: int | None,
) -> int:
    """Execute database migrations up to target_version (or latest)."""
    try:
        from job_automation.storage.engine import StorageEngine

        config, paths = load_config(
            config_path=config_path,
            data_root_override=data_root,
        )
        engine = StorageEngine.from_config(config, paths)
        try:
            applied = engine.migrate(target_version=target_version)
            current = engine.get_schema_version()
            print("Storage migration: SUCCESS")
            print(f"  Database Path:     {paths.database_path}")
            print(f"  Newly Applied:     {applied}")
            print(f"  Current Version:   {current}")
            return 0
        finally:
            engine.close()
    except Exception as exc:
        print(f"Storage migration: FAILED\n  Error: {exc}", file=sys.stderr)
        return 2


def run_storage_status(config_path: str | None, data_root: str | None) -> int:
    """Display database schema migration status."""
    try:
        from job_automation.storage.engine import StorageEngine
        from job_automation.storage.migrations import get_applied_migrations

        config, paths = load_config(
            config_path=config_path,
            data_root_override=data_root,
        )
        engine = StorageEngine.from_config(config, paths)
        try:
            current = engine.get_schema_version()
            applied = get_applied_migrations(engine.conn)
            print("Storage status: OK")
            print(f"  Database Path:     {paths.database_path}")
            print(f"  Current Version:   {current}")
            print(f"  Applied Count:     {len(applied)}")
            for v, meta in applied.items():
                print(f"    v{v} ({meta['name']}): applied at {meta['applied_at']}")
            return 0
        finally:
            engine.close()
    except Exception as exc:
        print(f"Storage status: FAILED\n  Error: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "config" and args.config_command == "check":
        return run_config_check(args.config, args.data_root)

    if args.command == "storage":
        if args.storage_command == "migrate":
            return run_storage_migrate(args.config, args.data_root, args.target_version)
        if args.storage_command == "status":
            return run_storage_status(args.config, args.data_root)

    if args.command == "profile":
        from job_automation.profile.cli import handle_profile_commands

        return handle_profile_commands(args)

    if args.command == "policy":
        from job_automation.policy.cli import handle_policy_commands

        return handle_policy_commands(args)

    if args.command == "sources":
        from job_automation.sources.cli import handle_sources_commands

        return handle_sources_commands(args)

    if args.command == "identity":
        from job_automation.identity.cli import run_identity_command

        return run_identity_command(args)

    if args.command == "context":
        from job_automation.context.index_cli import handle_context_commands

        return handle_context_commands(args)

    if args.command == "run":
        from job_automation.orchestration.cli import handle_run_commands

        return handle_run_commands(args)

    if args.command == "evaluation":
        from job_automation.evaluation.cli import handle_evaluation_commands

        return handle_evaluation_commands(args)

    if args.command == "ops":
        from job_automation.operations.cli import handle_ops_commands

        return handle_ops_commands(args)

    if args.command == "generation":
        from job_automation.generation.cli import handle_generation_commands

        return handle_generation_commands(args)

    if args.command == "auto-draft":
        from job_automation.generation.automatic.cli import run_auto_draft_cli

        return run_auto_draft_cli(args)

    if args.command == "delivery":
        from job_automation.orchestration.summary_delivery.cli import handle_delivery_commands

        return handle_delivery_commands(args)

    # If no recognized command was supplied
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

