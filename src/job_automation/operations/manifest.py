"""Backup manifest construction, serialization, and discovery (OPS-01-S06)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_automation import __version__
from job_automation.operations.records import (
    BackupFileEntry,
    BackupManifest,
    ItemClass,
    RemoteRecoveryExport,
)
from job_automation.storage.migrations import ALL_MIGRATIONS


def build_backup_manifest(
    backup_id: uuid.UUID,
    source_data_root: Path | str,
    local_cut_time: datetime,
    schema_version: int,
    file_entries: list[BackupFileEntry],
    remote_export: RemoteRecoveryExport | None = None,
    failure_domain_evidence: dict[str, Any] | None = None,
    verification_results: dict[str, Any] | None = None,
) -> BackupManifest:
    """Construct an immutable BackupManifest record."""
    total_bytes = sum(f.size_bytes for f in file_entries)
    migration_checksums = {m.version: m.checksum for m in ALL_MIGRATIONS}

    if remote_export and remote_export.completeness_status.value == "complete":
        completeness = "complete_local_and_remote"
    else:
        completeness = "complete_local"

    return BackupManifest(
        backup_id=backup_id,
        created_at=datetime.now(timezone.utc),
        format_version="1.0",
        app_version=__version__,
        schema_version=schema_version,
        migration_checksums=migration_checksums,
        local_cut_time=local_cut_time,
        source_data_root=str(Path(source_data_root).resolve()),
        files=file_entries,
        total_files_count=len(file_entries),
        total_bytes=total_bytes,
        completeness_status=completeness,
        remote_export=remote_export,
        failure_domain_evidence=failure_domain_evidence or {},
        verification_results=verification_results or {},
    )


def save_manifest(manifest: BackupManifest, target_dir: Path) -> Path:
    """Serialize and write manifest.json to the target backup directory."""
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest_path


def load_manifest(backup_dir: Path | str) -> BackupManifest:
    """Read and validate manifest.json from a backup directory."""
    path = Path(backup_dir) / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Backup manifest not found in directory: {backup_dir}")
    content = path.read_text(encoding="utf-8")
    return BackupManifest.model_validate_json(content)

