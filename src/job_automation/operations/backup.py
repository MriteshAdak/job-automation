"""Complete, consistent local backup creation and pruning (OPS-01-S06).

Enforces:
- Maintenance lock excluding concurrent workers during snapshot and file copy.
- Online SQLite backup API ensuring all committed WAL transactions are captured.
- Mutually consistent copying of all referenced bulky raw and artifact files.
- Manifest generation with complete file hashes, migration checksums, and remote export metadata.
- Atomic commit from staging directory with completion marker.
- Safe pruning of expired completed backups while preserving recent and pinned sets.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.operations.capacity import measure_volume_capacity
from job_automation.operations.exceptions import BackupError
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.operations.manifest import build_backup_manifest, load_manifest, save_manifest
from job_automation.operations.paths import (
    check_destination_overlap,
    is_same_physical_device,
    validate_safe_path,
)
from job_automation.operations.records import (
    BackupFileEntry,
    BackupManifest,
    ItemClass,
    OperationsSettings,
    RemoteRecoveryExport,
)
from job_automation.operations.remote_export import assemble_remote_export
from job_automation.operations.verification import verify_backup
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine
from job_automation.storage.filestore import compute_sha256

logger = logging.getLogger(__name__)


def create_backup(
    settings: OperationsSettings,
    data_root: Path | str,
    engine: StorageEngine,
    destination_override: Path | str | None = None,
    local_only: bool = False,
    sync_config: SyncMappingConfig | None = None,
    export_dir: Path | str | None = None,
) -> tuple[BackupManifest, Path]:
    """Create a complete, consistent backup set in staging then commit to destination."""
    root = Path(data_root).resolve()

    # 1. Resolve destination
    raw_dest = destination_override or settings.backup.destination or (root / "backups")
    dest = Path(raw_dest).resolve()
    check_destination_overlap(root, dest)
    dest.mkdir(parents=True, exist_ok=True)

    # 2. Check destination capacity preflight
    rep, issues = measure_volume_capacity(
        target_path=dest,
        required_bytes=50 * 1024 * 1024,  # minimum preflight reserve check
        settings=settings.capacity,
        reference_path=root,
    )
    if rep.status.value == "blocked":
        raise BackupError(
            f"Backup preflight capacity check failed on '{dest}': free space is below required reserve.",
            category=ErrorCategory.CAPACITY,
        )

    # 3. Acquire maintenance exclusion lock BEFORE any database operations
    lock = WindowsWorkerLock(root)
    with lock.acquire(owner_kind=OwnerKind.MAINTENANCE, timeout_seconds=settings.limits.timeout_seconds):
        # 4. Assemble remote recovery export under maintenance lock
        if not local_only and sync_config is not None:
            remote_export: RemoteRecoveryExport | None = assemble_remote_export(
                engine, config=sync_config, export_dir=export_dir
            )
        else:
            remote_export = assemble_remote_export(engine, config=None, export_dir=export_dir)

        if settings.backup.require_remote_export and remote_export.completeness_status.value != "complete":
            raise BackupError(
                f"Remote Salesforce export completeness required by policy, but export status is '{remote_export.completeness_status.value}'.",
                category=ErrorCategory.VALIDATION,
            )

        cut_time = datetime.now(timezone.utc)
        backup_id = uuid.uuid4()
        staging_dir = dest / f".staging_{backup_id}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 5. Snapshot SQLite database via SQLite Online Backup API
            staging_db_dir = staging_dir / "database"
            staging_db_dir.mkdir(parents=True, exist_ok=True)
            staging_db_path = staging_db_dir / "job_automation.db"

            target_conn = sqlite3.connect(str(staging_db_path))
            try:
                engine.conn.backup(target_conn)
            finally:
                target_conn.close()

            # Record database file in file entries
            db_bytes = staging_db_path.read_bytes()
            db_hash = compute_sha256(db_bytes)
            db_rel = engine.db_path.resolve().relative_to(root).as_posix()

            file_entries: list[BackupFileEntry] = [
                BackupFileEntry(
                    root_relative_path=db_rel,
                    sha256=db_hash,
                    size_bytes=len(db_bytes),
                    item_class=ItemClass.DATABASE,
                )
            ]

            # 6. Copy retained managed files (raw, artifacts, profiles, indexes)
            inv_mgr = RetentionInventoryManager(root)
            inv = inv_mgr.build_inventory(engine)

            for item in inv.items:
                if item.item_class == ItemClass.DATABASE:
                    continue  # already handled via backup API

                src_file = validate_safe_path(item.root_relative_path, root)
                if not src_file.is_file():
                    continue

                # Exclude backup folder, locks, staging, quarantine
                if item.root_relative_path.startswith("backups/") or item.root_relative_path.startswith("."):
                    continue

                dst_file = staging_dir / item.root_relative_path
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_file), str(dst_file))

                # Verify copied bytes
                copied_bytes = dst_file.read_bytes()
                copied_hash = compute_sha256(copied_bytes)

                file_entries.append(
                    BackupFileEntry(
                        root_relative_path=item.root_relative_path,
                        sha256=copied_hash,
                        size_bytes=len(copied_bytes),
                        item_class=item.item_class,
                    )
                )

            # Copy remote export files if an export directory was included
            if export_dir is not None:
                exp_path = Path(export_dir).resolve()
                if exp_path.is_dir():
                    for exp_file in sorted(exp_path.rglob("*")):
                        if exp_file.is_file():
                            rel_to_exp = exp_file.relative_to(exp_path).as_posix()
                            backup_rel = f"remote_export/{rel_to_exp}"
                            dst_exp = staging_dir / backup_rel
                            dst_exp.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(exp_file), str(dst_exp))
                            exp_bytes = dst_exp.read_bytes()
                            file_entries.append(
                                BackupFileEntry(
                                    root_relative_path=backup_rel,
                                    sha256=compute_sha256(exp_bytes),
                                    size_bytes=len(exp_bytes),
                                    item_class=ItemClass.METADATA,
                                )
                            )

            # 7. Physical failure domain evidence
            is_same, reason = is_same_physical_device(dest, root)
            failure_domain = {
                "is_same_disk": is_same,
                "reason": reason,
                "destination_path": str(dest),
                "source_data_root": str(root),
            }

            verification_meta = {
                "sqlite_backup_api": "success",
                "files_copied": len(file_entries),
                "cut_timestamp": cut_time.isoformat(),
            }

            # 8. Manifest and completion marker
            manifest = build_backup_manifest(
                backup_id=backup_id,
                source_data_root=root,
                local_cut_time=cut_time,
                schema_version=engine.get_schema_version(),
                file_entries=file_entries,
                remote_export=remote_export,
                failure_domain_evidence=failure_domain,
                verification_results=verification_meta,
            )

            save_manifest(manifest, staging_dir)
            (staging_dir / "backup.complete").write_text(
                f"backup_id={backup_id}\ncut_time={cut_time.isoformat()}\n",
                encoding="utf-8",
            )

            # 9. Commit from staging to final generation
            gen_dir_name = f"backup_{backup_id}_{cut_time.strftime('%Y%m%dT%H%M%SZ')}"
            final_backup_dir = dest / gen_dir_name
            shutil.move(str(staging_dir), str(final_backup_dir))

        except Exception as exc:
            # Clean up incomplete staging directory
            if staging_dir.exists():
                shutil.rmtree(str(staging_dir), ignore_errors=True)
            raise BackupError(f"Backup creation failed: {exc}") from exc

    # 10. Verify final committed backup
    is_valid, verify_issues = verify_backup(final_backup_dir)
    if not is_valid:
        raise BackupError(
            f"Backup verification failed on committed set: {verify_issues}",
            category=ErrorCategory.VALIDATION,
        )

    # 11. Record backup in operations database
    engine.operations.save_backup_record(
        backup_id=backup_id,
        created_at=manifest.created_at.isoformat(),
        backup_path=str(final_backup_dir),
        format_version=manifest.format_version,
        app_version=manifest.app_version,
        schema_version=manifest.schema_version,
        completeness_status=manifest.completeness_status,
        manifest_json=manifest.model_dump_json(),
        status="complete",
        verified_at=datetime.now(timezone.utc).isoformat(),
    )

    # 12. Prune old backups
    try:
        prune_backups(dest=dest, settings=settings, engine=engine)
    except Exception as exc:
        logger.warning("Backup pruning encountered an issue: %s", exc)

    return manifest, final_backup_dir


def prune_backups(
    dest: Path,
    settings: OperationsSettings,
    engine: StorageEngine | None = None,
) -> int:
    """Safely remove old completed backup generations exceeding retention policy."""
    if not dest.is_dir():
        return 0

    keep_count = settings.backup.keep_generations
    max_days = settings.backup.max_age_days
    pinned = set(settings.backup.pinned_backups)

    # Find completed backup directories
    backup_dirs: list[tuple[datetime, Path, BackupManifest]] = []
    for item in dest.iterdir():
        if item.is_dir() and (item / "backup.complete").is_file() and (item / "manifest.json").is_file():
            try:
                mf = load_manifest(item)
                backup_dirs.append((mf.created_at, item, mf))
            except Exception:
                continue

    # Sort descending by creation date (newest first)
    backup_dirs.sort(key=lambda x: x[0], reverse=True)

    pruned = 0
    now_dt = datetime.now(timezone.utc)

    # Preserve at least `keep_count` most recent complete backups
    for idx, (created_at, b_dir, mf) in enumerate(backup_dirs):
        if idx < keep_count:
            continue

        if str(mf.backup_id) in pinned:
            continue

        age_days = (now_dt - created_at).total_seconds() / 86400.0
        if age_days >= max_days:
            try:
                shutil.rmtree(str(b_dir))
                pruned += 1
                if engine is not None:
                    engine.operations.update_backup_status(mf.backup_id, "pruned")
            except OSError as exc:
                logger.warning("Could not prune old backup %s: %s", b_dir, exc)

    return pruned

