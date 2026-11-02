"""Command-line interface for operations commands (OPS-01-S08).

Subcommands:
- capacity: Measure volume capacities and report operational headroom.
- cleanup preview: Inspect eligible retention candidates and produce a durable CleanupPlan.
- cleanup apply: Safely execute an exact reviewed CleanupPlan by ID and hash.
- backup create: Create and verify an atomic, consistent point-in-time backup.
- backup verify: Independently verify backup directory structure and file hashes.
- restore plan: Pre-flight and validate restoration into an isolated target root.
- restore apply: Restore from backup into target root and relocate database references.

Exit Codes:
  0: Complete requested scope / success.
  1: Partial or degraded execution (e.g. local-only backup, capacity warning).
  2: Invalid/missing configuration, invalid arguments, or stale/invalidated input.
  3: Operational or verification failure (capacity blocked, corrupt backup, IO error).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import sys
import uuid
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.contracts.errors import ErrorCategory
from job_automation.operations.backup import create_backup
from job_automation.operations.capacity import check_capacity
from job_automation.operations.cleanup import apply_cleanup
from job_automation.operations.exceptions import (
    BackupError,
    OperationsError,
    PlanInvalidatedError,
    RestoreError,
)
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.operations.preview import generate_cleanup_preview
from job_automation.operations.records import (
    CapacityStatus,
    CleanupResult,
    OperationStatus,
    OperationsSettings,
    RemoteCompleteness,
)
from job_automation.operations.restore import apply_restore, plan_restore
from job_automation.operations.scheduling.service import SchedulingService
from job_automation.operations.settings import load_operations_settings
from job_automation.operations.verification import verify_backup
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


def register_ops_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'ops' command group and its subcommands."""
    ops_parser = subparsers.add_parser(
        "ops",
        help="System operations: capacity, retention cleanup, backup, and restore",
    )
    ops_sub = ops_parser.add_subparsers(dest="ops_command", help="Operations actions")

    # 1. capacity
    cap_p = ops_sub.add_parser("capacity", help="Check storage volume capacity and headroom")
    cap_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    cap_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    cap_p.add_argument("--destination", type=str, default=None, help="Override backup destination path")
    cap_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 2. cleanup
    clean_p = ops_sub.add_parser("cleanup", help="Retention cleanup preview and apply")
    clean_sub = clean_p.add_subparsers(dest="cleanup_command", help="Cleanup actions")

    # cleanup preview
    prev_p = clean_sub.add_parser("preview", help="Generate inspectable cleanup preview and plan")
    prev_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    prev_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    prev_p.add_argument("--cutoff-days", type=int, default=None, help="Override retention cutoff in days")
    prev_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # cleanup apply
    apply_clean_p = clean_sub.add_parser("apply", help="Apply a previously reviewed cleanup plan")
    apply_clean_p.add_argument("--plan", type=str, required=True, help="Cleanup plan UUID")
    apply_clean_p.add_argument("--plan-hash", type=str, required=True, help="Expected plan SHA-256 hash")
    apply_clean_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    apply_clean_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    apply_clean_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 3. backup
    bak_p = ops_sub.add_parser("backup", help="Point-in-time backup creation and verification")
    bak_sub = bak_p.add_subparsers(dest="backup_command", help="Backup actions")

    # backup create
    create_bak_p = bak_sub.add_parser("create", help="Create a consistent point-in-time backup")
    create_bak_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    create_bak_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    create_bak_p.add_argument("--destination", type=str, default=None, help="Override backup destination directory")
    create_bak_p.add_argument(
        "--local-only",
        action="store_true",
        help="Create backup even if remote Salesforce coverage is absent/incomplete",
    )
    create_bak_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # backup verify
    ver_bak_p = bak_sub.add_parser("verify", help="Verify integrity of an existing backup")
    ver_bak_p.add_argument("--backup-dir", type=str, required=True, help="Path to backup directory to verify")
    ver_bak_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 4. restore
    res_p = ops_sub.add_parser("restore", help="Disaster recovery restore into isolation")
    res_sub = res_p.add_subparsers(dest="restore_command", help="Restore actions")

    # restore plan
    plan_res_p = res_sub.add_parser("plan", help="Pre-flight and validate restoration into target directory")
    plan_res_p.add_argument("--backup-dir", type=str, required=True, help="Path to backup directory")
    plan_res_p.add_argument("--target", type=str, required=True, help="Path to empty target data root")
    plan_res_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    plan_res_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # restore apply
    apply_res_p = res_sub.add_parser("apply", help="Execute restoration and database path relocation")
    apply_res_p.add_argument("--backup-dir", type=str, required=True, help="Path to backup directory")
    apply_res_p.add_argument("--target", type=str, required=True, help="Path to empty target data root")
    apply_res_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    apply_res_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 5. schedule (AUTO-01)
    sched_p = ops_sub.add_parser("schedule", help="Native Windows scheduling and startup operations")
    sched_sub = sched_p.add_subparsers(dest="schedule_command", help="Scheduling actions")

    # schedule status
    st_p = sched_sub.add_parser("status", help="Inspect scheduling status, definitions, and health")
    st_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    st_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    st_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # schedule evaluate
    ev_p = sched_sub.add_parser("evaluate", help="Dry-run evaluation of due/coalesced slots")
    ev_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    ev_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    ev_p.add_argument("--at-time", type=str, default=None, help="Evaluate as of specific ISO datetime")
    ev_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # schedule dispatch
    disp_p = sched_sub.add_parser("dispatch", help="Execute dispatcher to admit and run due slots")
    disp_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    disp_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    disp_p.add_argument("--as-of", type=str, default=None, help="Evaluation timestamp override (ISO format)")
    disp_p.add_argument("--force", action="store_true", help="Dispatch even if schedule is disabled")
    disp_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # schedule export-tasks
    exp_p = sched_sub.add_parser("export-tasks", help="Export Windows Task Scheduler XML definitions")
    exp_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    exp_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    exp_p.add_argument("--output-dir", type=str, default=None, help="Directory for generated task XML files")
    exp_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # schedule manifest
    man_p = sched_sub.add_parser("manifest", help="Produce non-secret execution identity and path manifest")
    man_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    man_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    man_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # schedule enable / disable
    en_p = sched_sub.add_parser("enable", help="Enable scheduling for this deployment")
    en_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    en_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    en_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    dis_p = sched_sub.add_parser("disable", help="Disable scheduling for this deployment")
    dis_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    dis_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    dis_p.add_argument("--json", action="store_true", help="Output results in JSON format")


def _emit_error(msg: str, category: str = "operational", code: str = "ERROR", as_json: bool = False) -> None:
    if as_json:
        print(
            json.dumps(
                {"status": "error", "category": category, "code": code, "message": msg},
                indent=2,
            ),
            file=sys.stderr,
        )
    else:
        print(f"Error [{code}]: {msg}", file=sys.stderr)


def _load_env(
    config_path: str | None,
    data_root: str | None,
    skip_migrate: bool = False,
) -> tuple[StorageEngine, OperationsSettings, Path]:
    """Load configuration, operations settings, and storage engine."""
    config, paths = load_config(config_path=config_path, data_root_override=data_root)
    engine = StorageEngine.from_config(config, paths)
    if not skip_migrate:
        engine.migrate()

    base_dir = Path(config_path).parent if config_path else None
    settings = load_operations_settings(paths.operations_settings_path, base_dir=base_dir)
    return engine, settings, paths.data_root


def run_ops_capacity(args: argparse.Namespace) -> int:
    """Execute 'ops capacity' command."""
    as_json = getattr(args, "json", False)
    try:
        config, paths = load_config(config_path=args.config, data_root_override=args.data_root)
        base_dir = Path(args.config).parent if args.config else None
        settings = load_operations_settings(paths.operations_settings_path, base_dir=base_dir)

        dest = Path(args.destination) if args.destination else None
        if dest is None and settings.backup.destination:
            dest = Path(settings.backup.destination)

        report = check_capacity(
            settings=settings,
            source_root=paths.data_root,
            destination_path=dest,
        )

        if as_json:
            print(report.model_dump_json(indent=2))
        else:
            print("Storage Capacity Report")
            print("=======================")
            print(f"Overall Status:        {report.overall_status.value.upper()}")
            print(f"Source Volume:         {report.source_volume.volume_path} ({report.source_volume.status.value})")
            print(f"  Free Space:          {report.source_volume.free_bytes / (1024**3):.2f} GiB / {report.source_volume.total_bytes / (1024**3):.2f} GiB")
            print(f"  Required Reserve:    {report.source_volume.reserve_bytes / (1024**3):.2f} GiB")
            if report.destination_volume:
                print(f"Destination Volume:    {report.destination_volume.volume_path} ({report.destination_volume.status.value})")
                print(f"  Free Space:          {report.destination_volume.free_bytes / (1024**3):.2f} GiB / {report.destination_volume.total_bytes / (1024**3):.2f} GiB")
                print(f"  Required Reserve:    {report.destination_volume.reserve_bytes / (1024**3):.2f} GiB")
                print(f"  Shared Physical Disk:  {'Yes' if report.destination_volume.is_same_disk else 'No'}")
            else:
                print("Destination Volume:    Not configured")
            print(f"Remote (SF-04) Status: {report.remote_capacity.status.upper()}")
            if report.remote_capacity.notes:
                print(f"  Notes:               {report.remote_capacity.notes}")
            if report.issues:
                print("\nCapacity Issues:")
                for issue in report.issues:
                    print(f"  - [{issue.code}] {issue.message}")

        if report.overall_status == CapacityStatus.BLOCKED:
            return 3
        if report.overall_status == CapacityStatus.WARNING or report.remote_capacity.status == "unknown":
            return 1
        return 0

    except Exception as exc:
        _emit_error(str(exc), category="configuration", code="CAPACITY_CONFIG_ERROR", as_json=as_json)
        return 2


def run_ops_cleanup_preview(args: argparse.Namespace) -> int:
    """Execute 'ops cleanup preview' command."""
    as_json = getattr(args, "json", False)
    try:
        engine, settings, data_root = _load_env(args.config, args.data_root)
        try:
            if args.cutoff_days is not None:
                # Override raw_payloads_days for this preview
                retention_copy = settings.retention.model_copy(update={"raw_payloads_days": args.cutoff_days})
                settings = settings.model_copy(update={"retention": retention_copy})

            mgr = RetentionInventoryManager(data_root=data_root)
            inventory = mgr.build_inventory(engine)

            plan = generate_cleanup_preview(
                inventory=inventory,
                settings=settings,
                engine=engine,
            )

            if as_json:
                print(plan.model_dump_json(indent=2))
            else:
                print("Cleanup Preview (Retention Plan)")
                print("================================")
                print(f"Plan ID:               {plan.plan_id}")
                print(f"Plan Hash:             {plan.plan_hash}")
                print(f"Created At:            {plan.created_at.isoformat()}")
                print(f"Expires At:            {plan.expires_at.isoformat()}")
                print(f"Store Fingerprint:     {plan.store_fingerprint}")
                print(f"Policy Fingerprint:    {plan.policy_fingerprint}")
                print(f"Eligible Candidates:   {len(plan.candidates)}")
                print(f"Estimated Reclaim:     {plan.estimated_reclaim_bytes / 1024:.2f} KiB")
                print(f"Protected Items:       {plan.protected_items_count}")
                if plan.candidates:
                    print("\nCandidate Samples:")
                    for item in plan.candidates[:5]:
                        print(f"  [{item.item_class.value}] {item.root_relative_path} ({item.size_bytes} bytes)")
                    if len(plan.candidates) > 5:
                        print(f"  ... and {len(plan.candidates) - 5} more items.")
                print(f"\nTo apply this plan, run:\n  python -m job_automation ops cleanup apply --plan {plan.plan_id} --plan-hash {plan.plan_hash}")
            return 0
        finally:
            engine.close()

    except Exception as exc:
        _emit_error(str(exc), category="operational", code="CLEANUP_PREVIEW_ERROR", as_json=as_json)
        return 3


def run_ops_cleanup_apply(args: argparse.Namespace) -> int:
    """Execute 'ops cleanup apply' command."""
    as_json = getattr(args, "json", False)
    try:
        plan_uuid = uuid.UUID(args.plan)
    except ValueError:
        _emit_error(f"Invalid plan UUID: {args.plan}", category="configuration", code="INVALID_ARGUMENT", as_json=as_json)
        return 2

    try:
        engine, settings, data_root = _load_env(args.config, args.data_root)
        try:
            result = apply_cleanup(
                plan_id=plan_uuid,
                plan_hash=args.plan_hash,
                settings=settings,
                data_root=data_root,
                engine=engine,
            )

            if as_json:
                print(result.model_dump_json(indent=2))
            else:
                print("Cleanup Execution Result")
                print("========================")
                print(f"Plan ID:               {result.plan_id}")
                print(f"Status:                {result.status.value.upper()}")
                print(f"Items Removed:         {result.deleted_count}")
                print(f"Bytes Reclaimed:       {result.actual_reclaimed_bytes / 1024:.2f} KiB")
                if result.issues:
                    print("\nExecution Errors:")
                    for err in result.issues:
                        print(f"  - [{err.code}] {err.message}")

            if result.status == OperationStatus.SUCCEEDED:
                return 0
            if result.status == OperationStatus.PARTIAL:
                return 1
            return 3
        finally:
            engine.close()

    except PlanInvalidatedError as exc:
        _emit_error(exc.error.message, category="missing_configuration", code=exc.error.code, as_json=as_json)
        return 2
    except OperationsError as exc:
        code = exc.error.code if hasattr(exc, "error") else "CLEANUP_APPLY_ERROR"
        cat = exc.error.category if hasattr(exc, "error") else ErrorCategory.VALIDATION
        _emit_error(exc.error.message if hasattr(exc, "error") else str(exc), category=cat.value, code=code, as_json=as_json)
        if cat in (ErrorCategory.MISSING_CONFIGURATION, ErrorCategory.VALIDATION, ErrorCategory.UNSUPPORTED_INPUT, ErrorCategory.AUTHENTICATION):
            return 2
        return 3
    except Exception as exc:
        _emit_error(str(exc), category="validation", code="CLEANUP_APPLY_FAILED", as_json=as_json)
        return 3


def run_ops_backup_create(args: argparse.Namespace) -> int:
    """Execute 'ops backup create' command."""
    as_json = getattr(args, "json", False)
    try:
        engine, settings, data_root = _load_env(args.config, args.data_root, skip_migrate=True)
        try:
            dest_override = Path(args.destination) if args.destination else None
            manifest, backup_path = create_backup(
                settings=settings,
                data_root=data_root,
                engine=engine,
                destination_override=dest_override,
                local_only=args.local_only,
            )

            if as_json:
                print(manifest.model_dump_json(indent=2))
            else:
                print("Backup Creation Complete")
                print("========================")
                print(f"Backup ID:             {manifest.backup_id}")
                print(f"Location:              {backup_path}")
                print(f"Completeness Status:   {manifest.completeness_status.upper()}")
                print(f"Total Files:           {manifest.total_files_count}")
                print(f"Total Bytes:           {manifest.total_bytes / (1024**2):.2f} MiB")
                print(f"Remote Completeness:   {manifest.remote_export.completeness_status.value.upper()}")
                if manifest.completeness_status == "complete_local":
                    print("\nNOTE: Backup is LOCAL-ONLY. Salesforce remote recovery export was absent or incomplete.")

            if manifest.completeness_status == "complete_local" or manifest.remote_export.completeness_status != RemoteCompleteness.COMPLETE:
                return 1
            return 0
        finally:
            engine.close()

    except BackupError as exc:
        cat = exc.error.category if hasattr(exc, "error") else ErrorCategory.VALIDATION
        code = exc.error.code if hasattr(exc, "error") else "BACKUP_ERROR"
        _emit_error(exc.error.message, category=cat.value, code=code, as_json=as_json)
        if cat in (ErrorCategory.MISSING_CONFIGURATION, ErrorCategory.VALIDATION, ErrorCategory.UNSUPPORTED_INPUT, ErrorCategory.AUTHENTICATION):
            return 2
        return 3
    except Exception as exc:
        _emit_error(str(exc), category="validation", code="BACKUP_FAILED", as_json=as_json)
        return 3


def run_ops_backup_verify(args: argparse.Namespace) -> int:
    """Execute 'ops backup verify' command."""
    as_json = getattr(args, "json", False)
    backup_path = Path(args.backup_dir)
    if not backup_path.exists():
        _emit_error(f"Backup directory not found: {backup_path}", category="missing_configuration", code="BACKUP_DIR_NOT_FOUND", as_json=as_json)
        return 2

    try:
        from job_automation.operations.manifest import load_manifest

        is_valid, issues = verify_backup(backup_path)
        manifest = None
        try:
            manifest = load_manifest(backup_path)
        except Exception:
            pass

        if not is_valid:
            msg = "; ".join(issues)
            _emit_error(msg, category="validation", code="BACKUP_INTEGRITY_FAILED", as_json=as_json)
            return 3

        if as_json:
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "backup_id": str(manifest.backup_id) if manifest else "unknown",
                        "completeness_status": manifest.completeness_status if manifest else "unknown",
                        "total_files": manifest.total_files_count if manifest else 0,
                        "total_bytes": manifest.total_bytes if manifest else 0,
                        "issues": issues,
                    },
                    indent=2,
                )
            )
        else:
            print("Backup Verification: PASSED")
            print("===========================")
            if manifest:
                print(f"Backup ID:             {manifest.backup_id}")
                print(f"Completeness:          {manifest.completeness_status.upper()}")
                print(f"Total Files Verified:  {manifest.total_files_count}")
                print(f"Total Size:            {manifest.total_bytes / (1024**2):.2f} MiB")
                print(f"Format Version:        {manifest.format_version}")
        return 0

    except BackupError as exc:
        cat = exc.error.category if hasattr(exc, "error") else ErrorCategory.VALIDATION
        code = exc.error.code if hasattr(exc, "error") else "VERIFICATION_FAILED"
        _emit_error(exc.error.message, category=cat.value, code=code, as_json=as_json)
        if cat in (ErrorCategory.MISSING_CONFIGURATION, ErrorCategory.VALIDATION, ErrorCategory.UNSUPPORTED_INPUT):
            return 2
        return 3
    except Exception as exc:
        _emit_error(str(exc), category="validation", code="VERIFICATION_FAILED", as_json=as_json)
        return 3


def run_ops_restore_plan(args: argparse.Namespace) -> int:
    """Execute 'ops restore plan' command."""
    as_json = getattr(args, "json", False)
    backup_dir = Path(args.backup_dir)
    target_root = Path(args.target)

    if not backup_dir.exists():
        _emit_error(f"Backup directory not found: {backup_dir}", category="missing_configuration", code="BACKUP_DIR_NOT_FOUND", as_json=as_json)
        return 2

    try:
        settings = OperationsSettings()
        if args.config:
            config, paths = load_config(config_path=args.config)
            base_dir = Path(args.config).parent if args.config else None
            settings = load_operations_settings(paths.operations_settings_path, base_dir=base_dir)

        plan = plan_restore(backup_path=backup_dir, target_data_root=target_root, settings=settings)

        if not plan.is_valid:
            if as_json:
                print(plan.model_dump_json(indent=2))
            else:
                print("Restore Plan Pre-flight: INVALID")
                print("================================")
                print(f"Plan ID:               {plan.plan_id}")
                print(f"Backup ID:             {plan.backup_id}")
                print(f"Target Data Root:      {plan.target_data_root}")
                print(f"Capacity Status:       {plan.capacity_status.value.upper()}")
                print("\nConflicts / Blocking Reasons:")
                for c in plan.conflicts:
                    print(f"  - {c}")
            return 2

        if as_json:
            print(plan.model_dump_json(indent=2))
        else:
            print("Restore Plan Pre-flight: VALID")
            print("==============================")
            print(f"Plan ID:               {plan.plan_id}")
            print(f"Backup ID:             {plan.backup_id}")
            print(f"Source Data Root:      {plan.source_data_root}")
            print(f"Target Data Root:      {plan.target_data_root}")
            print(f"Total Files to Copy:   {plan.files_to_restore}")
            print(f"Total Required Bytes:  {plan.total_bytes / (1024**2):.2f} MiB")
            print(f"Capacity Status:       {plan.capacity_status.value.upper()}")
            print(f"\nTo apply this restoration into isolation, run:\n  python -m job_automation ops restore apply --backup-dir {backup_dir} --target {target_root}")
        return 0

    except RestoreError as exc:
        cat = exc.error.category if hasattr(exc, "error") else ErrorCategory.VALIDATION
        code = exc.error.code if hasattr(exc, "error") else "RESTORE_PLAN_ERROR"
        _emit_error(exc.error.message, category=cat.value, code=code, as_json=as_json)
        if cat in (ErrorCategory.MISSING_CONFIGURATION, ErrorCategory.VALIDATION, ErrorCategory.UNSUPPORTED_INPUT):
            return 2
        return 3
    except Exception as exc:
        _emit_error(str(exc), category="validation", code="RESTORE_PLAN_FAILED", as_json=as_json)
        return 3


def run_ops_restore_apply(args: argparse.Namespace) -> int:
    """Execute 'ops restore apply' command."""
    as_json = getattr(args, "json", False)
    backup_dir = Path(args.backup_dir)
    target_root = Path(args.target)

    if not backup_dir.exists():
        _emit_error(f"Backup directory not found: {backup_dir}", category="missing_configuration", code="BACKUP_DIR_NOT_FOUND", as_json=as_json)
        return 2

    try:
        settings = OperationsSettings()
        if args.config:
            config, paths = load_config(config_path=args.config)
            base_dir = Path(args.config).parent if args.config else None
            settings = load_operations_settings(paths.operations_settings_path, base_dir=base_dir)

        plan = plan_restore(backup_path=backup_dir, target_data_root=target_root, settings=settings)
        result = apply_restore(plan=plan, settings=settings)

        if as_json:
            print(result.model_dump_json(indent=2))
        else:
            print("Restore Execution Complete")
            print("==========================")
            print(f"Plan ID:               {result.plan_id}")
            print(f"Status:                {result.status.value.upper()}")
            print(f"Target Root:           {result.target_data_root}")
            print(f"Files Restored:        {result.restored_files_count}")
            print(f"Paths Relocated:       {result.relocated_paths_count}")
            print(f"SQLite Integrity:      {'PASSED' if result.integrity_check_passed else 'FAILED'}")
            print(f"Foreign Keys:          {'PASSED' if result.foreign_key_check_passed else 'FAILED'}")
            print("\nNext Activation Steps:")
            for step in result.activation_checklist:
                print(f"  [ ] {step}")
            if result.issues:
                print("\nRestore Errors:")
                for err in result.issues:
                    print(f"  - [{err.code}] {err.message}")

        if result.status == OperationStatus.SUCCEEDED:
            return 0
        if result.status == OperationStatus.PARTIAL:
            return 1
        return 3

    except RestoreError as exc:
        cat = exc.error.category if hasattr(exc, "error") else ErrorCategory.VALIDATION
        code = exc.error.code if hasattr(exc, "error") else "RESTORE_APPLY_ERROR"
        _emit_error(exc.error.message, category=cat.value, code=code, as_json=as_json)
        if cat in (ErrorCategory.MISSING_CONFIGURATION, ErrorCategory.VALIDATION, ErrorCategory.UNSUPPORTED_INPUT):
            return 2
        return 3
    except Exception as exc:
        _emit_error(str(exc), category="validation", code="RESTORE_APPLY_FAILED", as_json=as_json)
        return 3


def run_ops_schedule_status(args: argparse.Namespace) -> int:
    """Execute 'ops schedule status' command."""
    as_json = getattr(args, "json", False)
    try:
        service = SchedulingService(config_path=args.config, data_root=args.data_root)
        status = service.inspect_status()
        if as_json:
            print(json.dumps(status, indent=2))
        else:
            print("Scheduling Status Report")
            print("========================")
            print(f"Deployment ID:        {status['deployment_id']}")
            print(f"Data Root:            {status['data_root']}")
            print(f"Timezone:             {status['timezone']}")
            print(f"Schedule Active:      {'YES' if status['enabled'] else 'NO (Disabled)'}")
            print(f"Work Kind:            {status['work_kind']}")
            print(f"Target Times:         {', '.join(status['target_times'])}")
            print(f"Assessment Mode:      {status['assessment_mode']}")
            print(f"LLM Strategy:         {status['llm_strategy']}")
            print(f"Model Service URL:    {status['model_service_url']}")
            model = status["model_status"]
            print(f"Model Readiness:      {'READY' if model['is_ready'] else 'NOT READY'} ({model['category']})")
            if model.get("details"):
                print(f"  Details:            {model['details']}")
            if status.get("last_launch"):
                ll = status["last_launch"]
                print("\nLast Launch Attempt:")
                print(f"  Launch ID:          {ll['launch_id']}")
                print(f"  Started At:         {ll['started_at']}")
                print(f"  Outcome:            {ll['outcome']}")
                print(f"  Exit Code:          {ll['exit_code']}")
                print(f"  Run ID:             {ll['application_run_id']}")
            if status.get("recent_occurrences"):
                print("\nRecent Occurrences:")
                for o in status["recent_occurrences"]:
                    print(f"  - Slot: {o['slot']} | Outcome: {o['outcome']} | Run ID: {o['admitted_run_id']} | Retries: {o['retry_count']}")
        return 0
    except Exception as exc:
        _emit_error(str(exc), category="validation", code="SCHEDULE_STATUS_FAILED", as_json=as_json)
        return 2


def run_ops_schedule_evaluate(args: argparse.Namespace) -> int:
    """Execute 'ops schedule evaluate' command."""
    as_json = getattr(args, "json", False)
    try:
        at_time = None
        if getattr(args, "at_time", None):
            at_time = datetime.fromisoformat(args.at_time)
            if at_time.tzinfo is None:
                at_time = at_time.replace(tzinfo=timezone.utc)

        service = SchedulingService(config_path=args.config, data_root=args.data_root)
        preview = service.evaluate_preview(as_of_utc=at_time)
        if as_json:
            print(json.dumps(preview, indent=2))
        else:
            print("Schedule Evaluation Preview")
            print("===========================")
            print(f"Deployment ID:        {preview['deployment_id']}")
            print(f"As of (UTC):          {preview['as_of_utc']}")
            print(f"Schedule Enabled:     {preview['enabled']}")
            due = preview.get("due_occurrence")
            if due:
                print(f"Due Occurrence:       {due['intended_slot']} (UTC: {due['utc_instant']}, fold={due['fold']})")
                print(f"Occurrence ID:        {due['occurrence_id']}")
            else:
                print("Due Occurrence:       None")
            non_due = preview.get("coalesced_or_expired", [])
            if non_due:
                print(f"\nNon-due / Coalesced / Expired Slots ({len(non_due)}):")
                for nd in non_due:
                    print(f"  - Slot: {nd['intended_slot']} -> {nd['outcome']}")
        return 0
    except Exception as exc:
        _emit_error(str(exc), category="validation", code="SCHEDULE_EVALUATE_FAILED", as_json=as_json)
        return 2


def run_ops_schedule_dispatch(args: argparse.Namespace) -> int:
    """Execute 'ops schedule dispatch' command."""
    as_json = getattr(args, "json", False)
    try:
        as_of = None
        if getattr(args, "as_of", None):
            as_of = datetime.fromisoformat(args.as_of)
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)

        service = SchedulingService(config_path=args.config, data_root=args.data_root)
        report = service.dispatch_work(as_of_utc=as_of, force=getattr(args, "force", False))
        if as_json:
            print(report.model_dump_json(indent=2))
        else:
            print("Schedule Dispatch Execution")
            print("===========================")
            print(f"Status:               {report.status}")
            print(f"Exit Code:            {report.exit_code}")
            print(f"Message:              {report.message}")
            if report.occurrence_id:
                print(f"Occurrence ID:        {report.occurrence_id}")
            if report.run_id:
                print(f"Admitted Run ID:      {report.run_id}")
            if report.launch_id:
                print(f"Launch Attempt ID:    {report.launch_id}")
        return report.exit_code
    except Exception as exc:
        _emit_error(str(exc), category="operational", code="SCHEDULE_DISPATCH_FAILED", as_json=as_json)
        return 2


def run_ops_schedule_export_tasks(args: argparse.Namespace) -> int:
    """Execute 'ops schedule export-tasks' command."""
    as_json = getattr(args, "json", False)
    try:
        out_dir = getattr(args, "output_dir", None) or "config/tasks"
        service = SchedulingService(config_path=args.config, data_root=args.data_root)
        paths_dict = service.export_task_definitions(output_dir=out_dir)
        if as_json:
            print(json.dumps(paths_dict, indent=2))
        else:
            print("Task Scheduler XML Export Complete")
            print("==================================")
            print(f"Dispatcher XML:       {paths_dict['dispatcher_xml']}")
            print(f"Model Supervisor XML: {paths_dict['model_supervisor_xml']}")
        return 0
    except Exception as exc:
        _emit_error(str(exc), category="operational", code="SCHEDULE_EXPORT_FAILED", as_json=as_json)
        return 2


def run_ops_schedule_manifest(args: argparse.Namespace) -> int:
    """Execute 'ops schedule manifest' command."""
    as_json = getattr(args, "json", False)
    try:
        service = SchedulingService(config_path=args.config, data_root=args.data_root)
        manifest = service.generate_manifest()
        if as_json:
            print(manifest.model_dump_json(indent=2))
        else:
            print("Execution Identity & Path Manifest")
            print("==================================")
            print(f"Account Name:         {manifest.account_name}")
            print(f"Logon Type:           {manifest.logon_type}")
            print(f"Python Executable:    {manifest.python_executable}")
            print(f"Package Root:         {manifest.package_root}")
            print(f"Data Root:            {manifest.data_root}")
            print(f"Model Service URL:    {manifest.model_service_url}")
            print(f"Model Binary Path:    {manifest.model_binary_path or 'Not found'}")
            print(f"Batch Logon Verified: {'YES' if manifest.is_batch_logon_verified else 'NO (Pending host drill)'}")
            print("\nACL Resource Matrix:")
            for res_path, req_perm in manifest.acl_matrix.items():
                print(f"  - {res_path}: {req_perm}")
        return 0
    except Exception as exc:
        _emit_error(str(exc), category="operational", code="SCHEDULE_MANIFEST_FAILED", as_json=as_json)
        return 2


def run_ops_schedule_enable(args: argparse.Namespace) -> int:
    """Execute 'ops schedule enable' command."""
    as_json = getattr(args, "json", False)
    try:
        service = SchedulingService(config_path=args.config, data_root=args.data_root)
        updated = service.set_enabled(True)
        if as_json:
            print(json.dumps({"status": "ok", "schedule_id": updated.schedule_id, "enabled": True}, indent=2))
        else:
            print(f"Schedule '{updated.schedule_id}' is now ENABLED.")
        return 0
    except Exception as exc:
        _emit_error(str(exc), category="operational", code="SCHEDULE_ENABLE_FAILED", as_json=as_json)
        return 2


def run_ops_schedule_disable(args: argparse.Namespace) -> int:
    """Execute 'ops schedule disable' command."""
    as_json = getattr(args, "json", False)
    try:
        service = SchedulingService(config_path=args.config, data_root=args.data_root)
        updated = service.set_enabled(False)
        if as_json:
            print(json.dumps({"status": "ok", "schedule_id": updated.schedule_id, "enabled": False}, indent=2))
        else:
            print(f"Schedule '{updated.schedule_id}' is now DISABLED.")
        return 0
    except Exception as exc:
        _emit_error(str(exc), category="operational", code="SCHEDULE_DISABLE_FAILED", as_json=as_json)
        return 2


def handle_ops_commands(args: argparse.Namespace) -> int:
    """Dispatch parsed ops commands."""
    cmd = getattr(args, "ops_command", None)

    if cmd == "capacity":
        return run_ops_capacity(args)

    if cmd == "cleanup":
        c_cmd = getattr(args, "cleanup_command", None)
        if c_cmd == "preview":
            return run_ops_cleanup_preview(args)
        if c_cmd == "apply":
            return run_ops_cleanup_apply(args)

    if cmd == "backup":
        b_cmd = getattr(args, "backup_command", None)
        if b_cmd == "create":
            return run_ops_backup_create(args)
        if b_cmd == "verify":
            return run_ops_backup_verify(args)

    if cmd == "restore":
        r_cmd = getattr(args, "restore_command", None)
        if r_cmd == "plan":
            return run_ops_restore_plan(args)
        if r_cmd == "apply":
            return run_ops_restore_apply(args)

    if cmd == "schedule":
        s_cmd = getattr(args, "schedule_command", None)
        if s_cmd == "status":
            return run_ops_schedule_status(args)
        if s_cmd == "evaluate":
            return run_ops_schedule_evaluate(args)
        if s_cmd == "dispatch":
            return run_ops_schedule_dispatch(args)
        if s_cmd == "export-tasks":
            return run_ops_schedule_export_tasks(args)
        if s_cmd == "manifest":
            return run_ops_schedule_manifest(args)
        if s_cmd == "enable":
            return run_ops_schedule_enable(args)
        if s_cmd == "disable":
            return run_ops_schedule_disable(args)

    print("No valid ops subcommand specified. Use --help for usage.", file=sys.stderr)
    return 2
