"""Native Windows path safety, traversal validation, and volume analysis (OPS-01-S02).

Enforces:
- Strict path confinement beneath managed bases without junction/reparse-point escapes.
- Safe root-relative forward-slash manifest path conversions.
- Rejection of destination overlap with managed payload directories.
- Physical volume independence detection across Windows drive letters and mounts.
"""

from __future__ import annotations

import os
from pathlib import Path


def validate_safe_path(target_path: Path | str, base_dir: Path | str) -> Path:
    """Ensure target_path resolves strictly within base_dir without traversal or junction escape."""
    base = Path(base_dir).resolve()
    target = (base / Path(target_path)).resolve() if not Path(target_path).is_absolute() else Path(target_path).resolve()

    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"Path traversal or junction escape detected: '{target_path}' resolves to '{target}', which is outside base '{base}'"
        ) from exc

    return target


def normalize_manifest_path(target_path: Path | str, base_dir: Path | str) -> str:
    """Convert an absolute or relative path to a validated forward-slash root-relative path."""
    safe_target = validate_safe_path(target_path, base_dir)
    base = Path(base_dir).resolve()
    rel = safe_target.relative_to(base)
    return rel.as_posix()


def resolve_manifest_path(rel_path: str, base_dir: Path | str) -> Path:
    """Safely resolve a manifest's root-relative path against a base directory."""
    # Disallow absolute paths in manifest relative string
    p = Path(rel_path)
    if p.is_absolute() or rel_path.startswith("/") or rel_path.startswith("\\"):
        raise ValueError(f"Manifest path must be root-relative, got absolute path: '{rel_path}'")

    # Reject traversal tokens
    parts = p.parts
    if ".." in parts or "." in parts:
        raise ValueError(f"Manifest path contains invalid traversal elements: '{rel_path}'")

    return validate_safe_path(p, base_dir)


def check_destination_overlap(source_root: Path | str, destination_path: Path | str) -> None:
    """Ensure backup destination does not collide with managed payload directories."""
    src = Path(source_root).resolve()
    dst = Path(destination_path).resolve()

    if src == dst:
        raise ValueError(f"Backup destination cannot be identical to source data root: '{dst}'")

    # Forbidden subdirectories beneath source_root
    forbidden_subs = ["raw", "artifacts", "profiles", "indexes", "database", "logs"]
    for sub in forbidden_subs:
        payload_dir = (src / sub).resolve()
        if dst == payload_dir or payload_dir in dst.parents:
            raise ValueError(
                f"Backup destination '{dst}' overlaps with managed payload directory '{payload_dir}'. "
                "Destinations must not be placed inside raw, artifacts, profiles, indexes, or database folders."
            )


def is_same_physical_device(path1: Path | str, path2: Path | str) -> tuple[bool, str]:
    """Determine whether two paths share the same storage volume or device.

    Returns:
        (is_same_device: bool, classification_reason: str)
    """
    p1 = Path(path1).resolve()
    p2 = Path(path2).resolve()

    # On Windows, inspect drive letters / UNC shares
    drive1, rest1 = os.path.splitdrive(str(p1))
    drive2, rest2 = os.path.splitdrive(str(p2))

    drive1_norm = drive1.upper().rstrip(":")
    drive2_norm = drive2.upper().rstrip(":")

    if drive1_norm and drive2_norm:
        if drive1_norm == drive2_norm:
            return True, f"same_drive_letter ({drive1_norm}:)"
        else:
            # Different drive letters on Windows could still be partitions on the same physical disk,
            # so hardware independence is classified as 'unknown_hardware_different_letter'.
            return False, f"different_drive_letter ({drive1_norm}: vs {drive2_norm}:, physical independence unknown)"

    # UNC or POSIX mounts: compare st_dev
    try:
        s1 = p1.stat().st_dev
        s2 = p2.stat().st_dev
        if s1 == s2:
            return True, f"same_filesystem_device_id ({s1})"
        return False, f"different_filesystem_device_ids ({s1} vs {s2})"
    except Exception:
        return False, "unknown_mount"

